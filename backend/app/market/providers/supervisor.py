"""Reconnecting wrapper around any ``MarketDataProvider``.

State machine: DISCONNECTED -> CONNECTING -> CONNECTED -> (RECONNECTING | STALE) -> ...
An inner provider that reports UNCONFIGURED stops the supervisor (no retry storm). Nothing but
``CancelledError`` ever escapes ``stream()``/``connect()``/``subscribe()``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime

from app.market.providers.backoff import Backoff
from app.market.providers.base import MarketDataProvider
from app.market.settings import ReconnectConfig
from app.market.types import Bar, DataMode, ProviderHealth, ProviderName, ProviderState

logger = logging.getLogger(__name__)

_Sleep = Callable[[float], Awaitable[object]]


class SupervisedProvider:
    def __init__(
        self,
        factory: Callable[[], MarketDataProvider],
        reconnect: ReconnectConfig,
        *,
        is_active: Callable[[datetime], bool] = lambda ts: True,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        sleep: _Sleep = asyncio.sleep,
        backoff: Backoff | None = None,
    ) -> None:
        self._factory = factory
        self._cfg = reconnect
        self._is_active = is_active
        self._clock = clock
        self._sleep = sleep
        self._backoff = backoff if backoff is not None else Backoff(reconnect)
        self._backoff_dirty = False
        self._inner: MarketDataProvider = factory()
        self._inner_fresh = True  # first connect reuses the eagerly built inner
        self.name: ProviderName = self._inner.name
        self._state = ProviderState.DISCONNECTED
        self._symbols: list[str] = []
        self._attempts = 0
        self._messages = 0
        self._malformed_prev = 0
        self._last_error: str | None = None
        self._last_message_at: datetime | None = None
        self._connected_at: datetime | None = None
        self._retry_delay: float | None = None
        self._stopped = False

    # ------------------------------------------------------------------ public state

    @property
    def state(self) -> ProviderState:
        return self._state

    @property
    def attempts(self) -> int:
        """Cumulative reconnect attempts (failures that triggered a backoff sleep)."""
        return self._attempts

    def touch(self) -> None:
        """Record a received message: refreshes staleness, resets backoff, clears STALE."""
        self._last_message_at = self._clock()
        self._messages += 1
        if self._backoff_dirty:
            self._backoff.reset()
            self._backoff_dirty = False
        if self._state in (ProviderState.STALE, ProviderState.CONNECTING):
            self._state = ProviderState.CONNECTED

    def check_stale(self, now: datetime | None = None) -> bool:
        """Mark STALE when the market is active and no message for ``stale_after_s``.

        Returns True if currently STALE. Clears STALE when the market is inactive.
        """
        now = now if now is not None else self._clock()
        if self._state not in (
            ProviderState.CONNECTED,
            ProviderState.DEGRADED,
            ProviderState.STALE,
        ):
            return False
        if not self._is_active(now):
            if self._state == ProviderState.STALE:
                self._state = ProviderState.CONNECTED
            return False
        ref = self._last_message_at or self._connected_at
        if ref is not None and (now - ref).total_seconds() >= self._cfg.stale_after_s:
            self._state = ProviderState.STALE
            return True
        if self._state == ProviderState.STALE:
            self._state = ProviderState.CONNECTED
        return False

    def health(self) -> ProviderHealth:
        self.check_stale()
        try:
            inner = self._inner.health()
        except Exception:
            inner = ProviderHealth(
                provider=self.name,
                state=self._state,
                configured=self._state != ProviderState.UNCONFIGURED,
                mode=DataMode.LIVE,
            )
        state = self._state
        if state == ProviderState.CONNECTED and inner.state == ProviderState.DEGRADED:
            state = ProviderState.DEGRADED
        return inner.model_copy(
            update={
                "provider": self.name,
                "state": state,
                "last_message_at": self._last_message_at or inner.last_message_at,
                "last_error": self._last_error or inner.last_error,
                "reconnect_attempts": self._attempts,
                "subscribed_symbols": list(self._symbols),
                "messages_received": self._messages,
                "malformed_messages": self._malformed_prev + inner.malformed_messages,
            }
        )

    # ------------------------------------------------------------------ provider interface

    async def connect(self) -> None:
        """Try one connect. Never raises: failures are recorded and retried by ``stream()``."""
        self._stopped = False
        if self._state in (ProviderState.CONNECTED, ProviderState.UNCONFIGURED):
            return
        await self._open()

    async def disconnect(self) -> None:
        await self.stop()

    async def stop(self) -> None:
        self._stopped = True
        await self._safe_disconnect()
        if self._state != ProviderState.UNCONFIGURED:
            self._state = ProviderState.DISCONNECTED

    async def subscribe(self, symbols: list[str]) -> None:
        new = [s for s in dict.fromkeys(symbols) if s not in self._symbols]
        self._symbols.extend(new)
        if new and self._state == ProviderState.CONNECTED:
            try:
                await self._inner.subscribe(new)
            except Exception as exc:
                self._last_error = f"subscribe failed: {exc!r}"
                logger.warning("subscribe failed: %r", exc)

    async def unsubscribe(self, symbols: list[str]) -> None:
        gone = [s for s in symbols if s in self._symbols]
        self._symbols = [s for s in self._symbols if s not in gone]
        if gone and self._state == ProviderState.CONNECTED:
            try:
                await self._inner.unsubscribe(gone)
            except Exception as exc:
                self._last_error = f"unsubscribe failed: {exc!r}"
                logger.warning("unsubscribe failed: %r", exc)

    async def stream(self) -> AsyncIterator[Bar]:
        """Yield bars across reconnects. Ends on inner EOF, stop(), or UNCONFIGURED."""
        try:
            while not self._stopped and self._state != ProviderState.UNCONFIGURED:
                if self._retry_delay is not None:
                    delay, self._retry_delay = self._retry_delay, None
                    await self._sleep(delay)
                    if self._stopped:
                        break
                if self._state != ProviderState.CONNECTED and not await self._open():
                    continue
                it = self._inner.stream()
                try:
                    async for bar in it:
                        self.touch()
                        yield bar
                        if self._stopped:
                            return
                    # clean EOF (replay end / provider closed): stop, don't loop
                    if not self._stopped:
                        self._state = ProviderState.DISCONNECTED
                    return
                except Exception as exc:
                    if self._stopped:
                        return
                    self._fail(exc)
                    await self._safe_disconnect()
                finally:
                    aclose = getattr(it, "aclose", None)
                    if aclose is not None:
                        with contextlib.suppress(Exception):
                            await aclose()
        except asyncio.CancelledError:
            await self._safe_disconnect()
            if self._state != ProviderState.UNCONFIGURED:
                self._state = ProviderState.DISCONNECTED
            raise

    # ------------------------------------------------------------------ internals

    def _inner_unconfigured(self) -> bool:
        try:
            return self._inner.health().state == ProviderState.UNCONFIGURED
        except Exception:
            return False

    def _fail(self, exc: BaseException) -> None:
        self._last_error = f"{type(exc).__name__}: {exc}"
        self._attempts += 1
        self._backoff_dirty = True
        self._retry_delay = self._backoff.next()
        self._state = ProviderState.RECONNECTING
        logger.warning(
            "provider %s failed (%s); retry #%d in %.2fs",
            self.name,
            self._last_error,
            self._attempts,
            self._retry_delay,
        )

    async def _open(self) -> bool:
        """(Re)build inner if needed, connect, resubscribe. Returns True when CONNECTED."""
        self._state = ProviderState.CONNECTING
        try:
            if self._inner_fresh:
                self._inner_fresh = False
            else:
                await self._safe_disconnect()
                with contextlib.suppress(Exception):
                    self._malformed_prev += self._inner.health().malformed_messages
                self._inner = self._factory()
            if self._inner_unconfigured():
                return self._mark_unconfigured()
            await self._inner.connect()
            if self._symbols:
                await self._inner.subscribe(list(self._symbols))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if type(exc).__name__ == "ProviderUnconfigured" or self._inner_unconfigured():
                return self._mark_unconfigured()
            self._fail(exc)
            return False
        self._state = ProviderState.CONNECTED
        self._connected_at = self._clock()
        self._retry_delay = None
        return True

    def _mark_unconfigured(self) -> bool:
        self._state = ProviderState.UNCONFIGURED
        self._retry_delay = None
        logger.info("provider %s unconfigured; supervisor will not retry", self.name)
        return False

    async def _safe_disconnect(self) -> None:
        try:
            await self._inner.disconnect()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.debug("inner disconnect failed", exc_info=True)
