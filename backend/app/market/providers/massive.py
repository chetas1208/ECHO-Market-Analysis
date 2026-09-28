"""Massive (formerly Polygon.io) market-data adapter.

Wraps the official ``massive`` ``WebSocketClient`` (asyncio ``await client.connect(handler)``) and
normalizes per-minute aggregates (``AM.<SYM>``) to ECHO ``Bar`` objects. SDK model classes never
leave this module.

Wire fields of an ``AM`` message (SDK ``EquityAgg`` attribute in parentheses):
``ev`` (event_type), ``sym`` (symbol), ``o/h/l/c`` (open/high/low/close), ``v`` (volume),
``vw`` (vwap of this window), ``s``/``e`` (start_timestamp/end_timestamp, Unix ms),
``av`` (accumulated_volume), ``op`` (official_open_price), ``a`` (today's vwap, aggregate_vwap),
``z`` (average trade SIZE, not a trade count, so ``Bar.trade_count`` stays ``None``).

The SDK reconnects internally up to ``max_reconnects`` times and then re-raises; an outer
supervisor (``supervisor.py``) owns backoff/alerting. This provider surfaces that failure as a
``ConnectionError`` from ``stream()``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import re
from collections.abc import AsyncIterator, Callable, Iterable, Mapping
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any

from pydantic import ValidationError

from app.market.settings import get_market_settings
from app.market.types import Bar, DataMode, Interval, ProviderHealth, ProviderName, ProviderState

log = logging.getLogger(__name__)

AGG_MINUTE_EVENT = "AM"
DEFAULT_MAX_RECONNECTS = 3  # SDK-internal retries before surfacing the failure to the supervisor
DEFAULT_READY_TIMEOUT_S = 15.0
_READY_POLL_S = 0.05
_DROP_LOG_EVERY = 1000
_SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,14}$")
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

ClientFactory = Callable[..., Any]


class ProviderUnconfigured(Exception):
    """Raised by ``connect()`` when no API key is configured."""


# --------------------------------------------------------------------------- normalization


def _get(msg: Any, key: str, attr: str) -> Any:
    """Read a field from a wire dict (short key) or an SDK model object (attribute)."""
    if isinstance(msg, Mapping):
        return msg.get(key)
    return getattr(msg, attr, None)


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    f = float(value)
    return f if math.isfinite(f) else None


def _parse_agg(msg: Any, received_at: datetime) -> tuple[Bar | None, bool]:
    """Return ``(bar, malformed)``. Non-AM events are ignored: ``(None, False)``."""
    try:
        if msg is None or isinstance(msg, str | bytes | int | float | list | tuple):
            return None, True
        ev = _get(msg, "ev", "event_type")
        if isinstance(ev, Enum):
            ev = ev.value
        if ev is None:
            return None, True
        if ev != AGG_MINUTE_EVENT:
            return None, False

        symbol = _get(msg, "sym", "symbol")
        o, h, low, c = (
            _num(_get(msg, "o", "open")),
            _num(_get(msg, "h", "high")),
            _num(_get(msg, "l", "low")),
            _num(_get(msg, "c", "close")),
        )
        volume = _num(_get(msg, "v", "volume"))
        start_ms = _num(_get(msg, "s", "start_timestamp"))
        if (
            not isinstance(symbol, str) or None in (o, h, low, c, volume, start_ms) or start_ms <= 0  # type: ignore[operator]
        ):
            return None, True

        # Bar start = the aggregate window start, floored to the minute (AM windows are minute
        # aligned; flooring keeps the downstream aggregator's bucket invariant).
        start = _EPOCH + timedelta(milliseconds=int(start_ms))  # type: ignore[arg-type]
        start = start.replace(second=0, microsecond=0)

        vwap = _num(_get(msg, "vw", "vwap"))
        bar = Bar(
            symbol=symbol,
            timestamp=start,
            interval=Interval.M1,
            open=o,  # type: ignore[arg-type]
            high=h,  # type: ignore[arg-type]
            low=low,  # type: ignore[arg-type]
            close=c,  # type: ignore[arg-type]
            volume=volume,  # type: ignore[arg-type]
            vwap=vwap if vwap is not None and vwap > 0 else None,
            trade_count=None,
            source=ProviderName.MASSIVE,
            received_at=received_at,
        )
        return bar, False
    except (ValidationError, ValueError, OverflowError, TypeError, AttributeError):
        return None, True
    except Exception:  # pragma: no cover - defensive: normalization must never raise
        return None, True


def normalize_massive_agg(msg: Any, received_at: datetime) -> Bar | None:
    """Normalize one Massive ``AM`` message (SDK ``EquityAgg`` or wire dict) to a 1m ``Bar``.

    Pure; never raises. Returns ``None`` for malformed input and for non-``AM`` events.
    """
    return _parse_agg(msg, received_at)[0]


# --------------------------------------------------------------------------- provider


class _Eof:
    """Queue sentinel: clean end of stream."""


class _Failure:
    """Queue sentinel: the SDK task died; ``stream()`` raises ``ConnectionError``."""

    def __init__(self, message: str) -> None:
        self.message = message


def _default_client_factory(
    *, api_key: str, subscriptions: list[str], max_reconnects: int, feed: Any = None, **_: Any
) -> Any:
    from massive import WebSocketClient  # lazy: SDK stays inside the adapter
    from massive.websocket.models import Market

    kwargs: dict[str, Any] = {} if feed is None else {"feed": feed}
    return WebSocketClient(
        api_key=api_key,  # explicit: SDK default reads the env at import time
        market=Market.Stocks,
        subscriptions=subscriptions,
        verbose=False,
        max_reconnects=max_reconnects,
        **kwargs,
    )


def _topic(symbol: str) -> str:
    return f"{AGG_MINUTE_EVENT}.{symbol}"


def _clean_symbols(symbols: Iterable[str]) -> list[str]:
    out: list[str] = []
    for raw in symbols:
        s = raw.strip().upper()
        if not _SYMBOL_RE.match(s):  # rejects "*" (whole-market firehose) and junk
            raise ValueError(f"invalid symbol: {raw!r}")
        if s not in out:
            out.append(s)
    return out


class MassiveMarketDataProvider:
    """``MarketDataProvider`` backed by the Massive websocket (minute aggregates)."""

    name = ProviderName.MASSIVE

    def __init__(
        self,
        api_key: str | None,
        symbols: Iterable[str],
        *,
        client_factory: ClientFactory | None = None,
        queue_size: int | None = None,
        max_reconnects: int = DEFAULT_MAX_RECONNECTS,
        feed: Any = None,
        ready_timeout_s: float = DEFAULT_READY_TIMEOUT_S,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        key = api_key.strip() if api_key else ""
        self._api_key: str | None = key or None
        self._symbols: list[str] = _clean_symbols(symbols)
        self._factory: ClientFactory = client_factory or _default_client_factory
        self._queue_size = queue_size or get_market_settings().echo_market_queue_size
        self._max_reconnects = max_reconnects
        self._feed = feed
        self._ready_timeout_s = ready_timeout_s
        self._now: Callable[[], datetime] = clock or (lambda: datetime.now(UTC))

        self._client: Any = None
        self._task: asyncio.Task[None] | None = None
        self._queue: asyncio.Queue[Bar | _Eof | _Failure] = asyncio.Queue(self._queue_size)
        self._started = False
        self._terminal_sent = False
        self._ever_connected = False
        self._last_error: str | None = None
        self._last_message_at: datetime | None = None
        self._messages = 0
        self._malformed = 0
        self._dropped = 0
        self._connect_attempts = 0

    # -- introspection ------------------------------------------------------------------------

    @property
    def configured(self) -> bool:
        return self._api_key is not None

    @property
    def dropped(self) -> int:
        """Bars discarded (oldest first) because the internal queue was full."""
        return self._dropped

    @property
    def queue_depth(self) -> int:
        return self._queue.qsize()

    @property
    def queue_capacity(self) -> int:
        return self._queue_size

    def _authed(self) -> bool:
        c = self._client
        return (
            c is not None
            and getattr(c, "websocket", None) is not None
            and not getattr(c, "schedule_resub", True)
        )

    def _state(self) -> ProviderState:
        if not self.configured:
            return ProviderState.UNCONFIGURED
        task = self._task
        if task is None or task.done():
            return ProviderState.DISCONNECTED
        if self._authed():
            self._ever_connected = True
            return ProviderState.CONNECTED
        return ProviderState.RECONNECTING if self._ever_connected else ProviderState.CONNECTING

    def health(self) -> ProviderHealth:
        state = self._state()
        return ProviderHealth(
            provider=self.name,
            state=state,
            configured=self.configured,
            mode=DataMode.LIVE if state is ProviderState.CONNECTED else DataMode.OFFLINE,
            last_message_at=self._last_message_at,
            last_error=self._last_error,
            reconnect_attempts=self._connect_attempts,
            subscribed_symbols=list(self._symbols),
            messages_received=self._messages,
            malformed_messages=self._malformed,
        )

    # -- queue --------------------------------------------------------------------------------

    def _enqueue(self, item: Bar | _Eof | _Failure) -> None:
        """Bounded put: when full, drop the OLDEST item and count it."""
        while True:
            try:
                self._queue.put_nowait(item)
                return
            except asyncio.QueueFull:
                with contextlib.suppress(asyncio.QueueEmpty):
                    self._queue.get_nowait()
                    self._dropped += 1
                    if self._dropped == 1 or self._dropped % _DROP_LOG_EVERY == 0:
                        log.warning(
                            "massive queue full (cap=%d): dropped oldest bar (total dropped=%d)",
                            self._queue_size,
                            self._dropped,
                        )

    def _send_terminal(self, item: _Eof | _Failure) -> None:
        if not self._terminal_sent:
            self._terminal_sent = True
            self._enqueue(item)

    async def _handle(self, msgs: Any) -> None:
        """SDK message callback. Must never raise (it would kill the SDK connect loop)."""
        try:
            batch = msgs if isinstance(msgs, list | tuple) else [msgs]
            now = self._now()
            for m in batch:
                self._messages += 1
                self._last_message_at = now
                bar, malformed = _parse_agg(m, now)
                if malformed:
                    self._malformed += 1
                elif bar is not None:
                    self._enqueue(bar)
        except Exception:  # pragma: no cover - defensive
            self._malformed += 1
            log.exception("massive handler error")

    # -- lifecycle ----------------------------------------------------------------------------

    def _redact(self, text: str) -> str:
        return text.replace(self._api_key, "***") if self._api_key else text

    def _on_task_done(self, task: asyncio.Task[None]) -> None:
        if task.cancelled():
            self._send_terminal(_Eof())
            return
        exc = task.exception()
        if exc is None:
            self._send_terminal(_Eof())  # clean close (ConnectionClosedOK)
            return
        msg = self._redact(f"{type(exc).__name__}: {exc}")
        self._last_error = msg
        self._send_terminal(_Failure(msg))

    async def connect(self) -> None:
        if not self.configured:
            raise ProviderUnconfigured("MASSIVE_API_KEY is not set")
        if self._task is not None and not self._task.done():
            return  # already connected/connecting
        self._queue = asyncio.Queue(self._queue_size)
        self._terminal_sent = False
        self._started = True
        self._ever_connected = False
        self._last_error = None
        self._connect_attempts += 1
        client = self._factory(
            api_key=self._api_key,
            subscriptions=[_topic(s) for s in self._symbols],
            max_reconnects=self._max_reconnects,
            feed=self._feed,
        )
        self._client = client
        task = asyncio.create_task(client.connect(self._handle), name="massive-ws")
        task.add_done_callback(self._on_task_done)
        self._task = task
        try:
            await self._wait_ready(task)
        except BaseException:
            await self._teardown()
            raise

    async def _wait_ready(self, task: asyncio.Task[None]) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._ready_timeout_s
        while True:
            if task.done():
                if not task.cancelled() and task.exception() is not None:
                    raise ConnectionError(self._last_error or "massive connect failed")
                raise ConnectionError("massive connection closed during connect")
            if self._messages > 0 or self._authed():
                return
            if loop.time() >= deadline:
                self._last_error = "timed out waiting for massive auth/subscribe"
                raise ConnectionError(self._last_error)
            await asyncio.sleep(_READY_POLL_S)

    async def _teardown(self) -> None:
        client, task = self._client, self._task
        self._client = None
        if client is not None:
            with contextlib.suppress(Exception):
                await client.close()
        if task is not None and not task.done():
            task.cancel()
        if task is not None:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._task = None

    async def disconnect(self) -> None:
        """Close cleanly; idempotent. Ends any running ``stream()``."""
        await self._teardown()
        if self._started:
            self._send_terminal(_Eof())

    async def subscribe(self, symbols: list[str]) -> None:
        clean = [s for s in _clean_symbols(symbols) if s not in self._symbols]
        self._symbols.extend(clean)
        if clean and self._client is not None:
            self._client.subscribe(*[_topic(s) for s in clean])

    async def unsubscribe(self, symbols: list[str]) -> None:
        clean = [s for s in _clean_symbols(symbols) if s in self._symbols]
        self._symbols = [s for s in self._symbols if s not in clean]
        if clean and self._client is not None:
            self._client.unsubscribe(*[_topic(s) for s in clean])

    async def stream(self) -> AsyncIterator[Bar]:
        """Yield closed 1m bars. Ends on clean close; raises ``ConnectionError`` on link failure."""
        if not self.configured:
            raise ProviderUnconfigured("MASSIVE_API_KEY is not set")
        if not self._started:
            raise ConnectionError("massive provider not connected; call connect() first")
        queue = self._queue
        while True:
            item = await queue.get()
            if isinstance(item, _Eof):
                return
            if isinstance(item, _Failure):
                raise ConnectionError(item.message)
            yield item
