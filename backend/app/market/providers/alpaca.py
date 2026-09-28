"""Alpaca market-data adapter (secondary/fallback provider, D-009).

``alpaca.data.models.Bar`` objects never leave this module: they are normalized to ``Bar``.

Run model (verified against alpaca-py 0.44.0 ``alpaca/data/live/websocket.py``):
``StockDataStream.run()`` blocks and calls ``asyncio.run(self._run_forever())``. Driving the
private ``_run_forever()`` on OUR loop is unsafe: ``subscribe_*``/``unsubscribe_*`` on a running
stream call ``asyncio.run_coroutine_threadsafe(..., stream._loop).result()``, which deadlocks when
called from the loop that owns the stream. So the stream runs in a DEDICATED DAEMON THREAD via its
public ``run()`` (own event loop, built-in reconnect/backoff), handlers execute in that thread and
hand normalized bars to the caller's loop through ``loop.call_soon_threadsafe`` into a BOUNDED
queue (drop-oldest + counter). Runtime (un)subscribe and ``stop()`` (thread-safe) are called via
``asyncio.to_thread`` so they never block our loop. The only private attribute read is the
best-effort ``stream._running`` (true once the socket is authenticated and subscribed).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import threading
from collections import deque
from collections.abc import AsyncIterator, Callable, Iterable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from app.market.types import (
    Bar,
    DataMode,
    Interval,
    ProviderHealth,
    ProviderName,
    ProviderState,
)

log = logging.getLogger(__name__)

DEFAULT_QUEUE_SIZE = 5000
_WIRE_ALIASES = {
    "symbol": "S",
    "timestamp": "t",
    "open": "o",
    "high": "h",
    "low": "l",
    "close": "c",
    "volume": "v",
    "trade_count": "n",
    "vwap": "vw",
}
StreamFactory = Callable[[str, str, str], Any]


class ProviderUnconfigured(RuntimeError):
    """Raised by ``connect()`` when credentials are missing."""


def _field(bar: Any, name: str) -> Any:
    if isinstance(bar, Mapping):
        if name in bar:
            return bar[name]
        return bar.get(_WIRE_ALIASES[name])
    return getattr(bar, name, None)


def _num(v: Any) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def normalize_alpaca_bar(bar: Any, received_at: datetime | None = None) -> Bar | None:
    """Alpaca ``Bar`` model or dict -> ECHO ``Bar`` (1m, source ALPACA). Malformed -> None."""
    try:
        symbol = _field(bar, "symbol")
        ts = _field(bar, "timestamp")
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if not isinstance(symbol, str) or not isinstance(ts, datetime) or ts.tzinfo is None:
            return None
        o, h, lo, c, v = (_num(_field(bar, k)) for k in ("open", "high", "low", "close", "volume"))
        if None in (o, h, lo, c, v):
            return None
        vwap = _num(_field(bar, "vwap"))
        tc = _num(_field(bar, "trade_count"))
        return Bar(
            symbol=symbol,
            timestamp=ts.astimezone(UTC),
            interval=Interval.M1,
            open=o,  # type: ignore[arg-type]
            high=h,  # type: ignore[arg-type]
            low=lo,  # type: ignore[arg-type]
            close=c,  # type: ignore[arg-type]
            volume=v,  # type: ignore[arg-type]
            vwap=vwap if vwap and vwap > 0 else None,
            trade_count=round(tc) if tc is not None and tc >= 0 else None,
            source=ProviderName.ALPACA,
            received_at=received_at,
        )
    except Exception:
        return None


def _default_stream_factory(api_key: str, api_secret: str, feed: str) -> Any:
    from alpaca.data.enums import DataFeed
    from alpaca.data.live.stock import StockDataStream

    return StockDataStream(
        api_key, api_secret, feed=DataFeed.SIP if feed == "sip" else DataFeed.IEX
    )


def _norm_symbols(symbols: Iterable[str]) -> list[str]:
    out: list[str] = []
    for s in symbols:
        s = str(s).strip().upper()
        if s and s not in out:
            out.append(s)
    return out


class AlpacaMarketDataProvider:
    name = ProviderName.ALPACA

    def __init__(
        self,
        api_key: str | None,
        api_secret: str | None,
        feed: str = "iex",
        symbols: Sequence[str] = (),
        stream_factory: StreamFactory | None = None,
        queue_size: int = DEFAULT_QUEUE_SIZE,
        connect_timeout_s: float = 15.0,
        stop_timeout_s: float = 8.0,
    ) -> None:
        if queue_size < 1:
            raise ValueError("queue_size must be >= 1")
        self._key, self._secret = api_key or "", api_secret or ""
        self._feed = feed.lower()
        self._factory = stream_factory or _default_stream_factory
        self._symbols: list[str] = _norm_symbols(symbols)
        self._queue_size = queue_size
        self._connect_timeout = connect_timeout_s
        self._stop_timeout = stop_timeout_s
        self._configured = bool(self._key and self._secret)
        self._state = ProviderState.DISCONNECTED if self._configured else ProviderState.UNCONFIGURED
        self._stream: Any = None
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._buf: deque[Bar] = deque()
        self._wakeup: asyncio.Event | None = None
        self._lock = threading.Lock()
        self._stopping = False
        self._ended = False
        self._error: str | None = None
        self.dropped = 0
        self._messages = 0
        self._malformed = 0
        self._last_message_at: datetime | None = None

    # ---- lifecycle -------------------------------------------------------------------------
    async def connect(self) -> None:
        if not self._configured:
            raise ProviderUnconfigured("Alpaca credentials missing (ALPACA_API_KEY/SECRET)")
        if self._thread is not None and self._thread.is_alive():
            return
        self._loop = asyncio.get_running_loop()
        self._wakeup = asyncio.Event()
        self._buf.clear()
        self._stopping = self._ended = False
        self._error = None
        self._state = ProviderState.CONNECTING
        self._stream = self._factory(self._key, self._secret, self._feed)
        if self._symbols:
            self._stream.subscribe_bars(self._on_bar, *self._symbols)  # not running yet: safe
            await self._start_thread()

    async def _start_thread(self) -> None:
        """Start the stream thread, then wait until the socket is up (or fail loudly)."""
        stream = self._stream
        self._thread = threading.Thread(
            target=self._thread_main, args=(stream,), name="alpaca-stream", daemon=True
        )
        self._thread.start()
        deadline = self._loop.time() + self._connect_timeout  # type: ignore[union-attr]
        while not (getattr(stream, "_running", False) or self._messages):
            if not self._thread.is_alive() or self._loop.time() >= deadline:  # type: ignore[union-attr]
                err = self._error or "Alpaca stream did not become ready"
                await self.disconnect()
                self._error = err
                raise ConnectionError(err)
            await asyncio.sleep(0.02)
        self._state = ProviderState.CONNECTED

    def _thread_main(self, stream: Any) -> None:
        try:
            stream.run()  # blocks; owns its own loop; reconnects internally
            if not self._stopping:
                self._error = "Alpaca stream exited unexpectedly"
        except Exception as exc:
            self._error = f"{type(exc).__name__}: {exc}"
            log.warning("alpaca stream thread failed: %s", self._error)
        finally:
            self._call_in_loop(self._finish)

    def _call_in_loop(self, fn: Callable[..., None], *args: Any) -> None:
        loop = self._loop
        if loop is None:
            return
        with contextlib.suppress(RuntimeError):  # loop closed
            loop.call_soon_threadsafe(fn, *args)

    def _finish(self) -> None:
        """Loop-side: end-of-stream sentinel (+ state) once the stream thread is gone."""
        self._ended = True
        if not self._stopping and self._error:
            self._state = ProviderState.DEGRADED
        if self._wakeup is not None:
            self._wakeup.set()

    async def disconnect(self) -> None:
        """Idempotent. Stops the stream thread (thread-safe ``stop()``) and ends ``stream()``."""
        self._stopping = True
        stream, thread = self._stream, self._thread
        if thread is not None and stream is not None:
            await asyncio.to_thread(self._stop_and_join, stream, thread)
        self._stream, self._thread = None, None
        if self._configured:
            self._state = ProviderState.DISCONNECTED
        self._ended = True
        if self._wakeup is not None:
            self._wakeup.set()

    def _stop_and_join(self, stream: Any, thread: threading.Thread) -> None:
        # stop() needs stream._loop, which is not set until the thread's loop starts, and the
        # stream clears its stop flag when it starts: retry until the thread is gone.
        waited = 0.0
        while thread.is_alive() and waited < self._stop_timeout:
            with contextlib.suppress(Exception):  # not started yet / already closed
                stream.stop()
            thread.join(0.1)
            waited += 0.1
        if thread.is_alive():
            log.warning("alpaca stream thread did not stop within %.1fs", self._stop_timeout)

    # ---- subscriptions ---------------------------------------------------------------------
    async def subscribe(self, symbols: list[str]) -> None:
        new = [s for s in _norm_symbols(symbols) if s not in self._symbols]
        if not new:
            return
        self._symbols.extend(new)
        if self._stream is None:
            return  # applied at connect()
        if self._thread is None:
            self._stream.subscribe_bars(self._on_bar, *self._symbols)
            await self._start_thread()
        else:
            # running stream: subscribe blocks on the stream's loop -> keep off ours
            await asyncio.to_thread(self._stream.subscribe_bars, self._on_bar, *new)

    async def unsubscribe(self, symbols: list[str]) -> None:
        gone = [s for s in _norm_symbols(symbols) if s in self._symbols]
        if not gone:
            return
        self._symbols = [s for s in self._symbols if s not in gone]
        if self._stream is not None and self._thread is not None:
            await asyncio.to_thread(self._stream.unsubscribe_bars, *gone)

    # ---- data path -------------------------------------------------------------------------
    async def _on_bar(self, raw: Any) -> None:
        """Runs on the stream thread's loop. Normalize, count, hand off to our loop."""
        now = datetime.now(UTC)
        bar = normalize_alpaca_bar(raw, now)
        with self._lock:
            if bar is None:
                self._malformed += 1
                return
            self._messages += 1
            self._last_message_at = now
        self._call_in_loop(self._enqueue, bar)

    def _enqueue(self, bar: Bar) -> None:
        """Loop-side bounded put: drop OLDEST bar on overflow and count it."""
        while len(self._buf) >= self._queue_size:
            self._buf.popleft()
            self.dropped += 1
        self._buf.append(bar)
        if self._wakeup is not None:
            self._wakeup.set()

    @property
    def queue_depth(self) -> int:
        return len(self._buf)

    async def stream(self) -> AsyncIterator[Bar]:
        """Yield closed 1m bars. Ends after ``disconnect()``; raises ConnectionError if the
        stream thread died on its own."""
        if self._wakeup is None:
            raise ConnectionError("Alpaca provider not connected")
        while True:
            if self._buf:
                yield self._buf.popleft()
                continue
            if self._ended:  # drained; end (or fail) only after buffered bars were delivered
                if self._error and not self._stopping:
                    raise ConnectionError(self._error)
                return
            self._wakeup.clear()
            if self._buf or self._ended:
                continue
            await self._wakeup.wait()

    def health(self) -> ProviderHealth:
        state = self._state
        return ProviderHealth(
            provider=ProviderName.ALPACA,
            state=state,
            configured=self._configured,
            mode=DataMode.LIVE if state == ProviderState.CONNECTED else DataMode.OFFLINE,
            last_message_at=self._last_message_at,
            last_error=self._error,
            subscribed_symbols=list(self._symbols),
            messages_received=self._messages,
            malformed_messages=self._malformed,
        )
