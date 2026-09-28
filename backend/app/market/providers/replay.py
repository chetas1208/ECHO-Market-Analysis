"""Deterministic replay provider (no network). Data emitted here is ALWAYS labelled REPLAY.

Determinism notes:
- Bars are sorted once by (timestamp, symbol); the cursor never moves backwards, so a reconnect
  after ``fail_after`` continues exactly where the stream stopped (no repeat, no skip).
- ``received_at`` is set to the bar's own timestamp (not wall clock) so replays are byte-for-byte
  reproducible; ``source`` is forced to ``ProviderName.REPLAY``.
- ``fail_after`` is a one-shot failure simulation: after N bars have been yielded (cumulative)
  the stream raises ``ConnectionError`` once; the state becomes DISCONNECTED until ``connect()``.
- ``speed`` > 0 sleeps ``gap_seconds / speed`` between consecutive yielded bars with different
  timestamps (``speed=0`` means as fast as possible, no sleeping).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from datetime import datetime

from app.market.types import Bar, DataMode, ProviderHealth, ProviderName, ProviderState

SleepFn = Callable[[float], Awaitable[None]]


class ReplayMarketDataProvider:
    def __init__(
        self,
        bars: Sequence[Bar],
        speed: float = 0.0,
        name: ProviderName = ProviderName.REPLAY,
        fail_after: int | None = None,
        sleep: SleepFn = asyncio.sleep,
    ) -> None:
        if speed < 0:
            raise ValueError("speed must be >= 0")
        if fail_after is not None and fail_after < 0:
            raise ValueError("fail_after must be >= 0")
        self.name = name
        self._speed = speed
        self._sleep = sleep
        self._fail_after = fail_after
        self._bars: list[Bar] = sorted(bars, key=lambda b: (b.timestamp, b.symbol))
        self._all_symbols = sorted({b.symbol for b in self._bars})
        self._subscribed: set[str] | None = None  # None -> everything in the data
        self._state = ProviderState.DISCONNECTED
        self._pos = 0  # index of the next bar to consider
        self._yielded = 0
        self._failed = False
        self._stopped = False
        self._finished = False
        self._last_ts: datetime | None = None
        self._last_message_at: datetime | None = None
        self._last_error: str | None = None
        self._reconnects = 0

    @property
    def finished(self) -> bool:
        """True once the stream has reached the end of the data."""
        return self._finished

    async def connect(self) -> None:
        if self._state == ProviderState.DISCONNECTED and self._failed:
            self._reconnects += 1
        self._stopped = False
        self._last_error = None
        self._state = ProviderState.CONNECTED

    async def disconnect(self) -> None:
        self._stopped = True
        self._state = ProviderState.DISCONNECTED

    async def subscribe(self, symbols: list[str]) -> None:
        wanted = {s.strip().upper() for s in symbols}
        self._subscribed = wanted if self._subscribed is None else self._subscribed | wanted

    async def unsubscribe(self, symbols: list[str]) -> None:
        drop = {s.strip().upper() for s in symbols}
        base = set(self._all_symbols) if self._subscribed is None else self._subscribed
        self._subscribed = base - drop

    def _wanted(self, symbol: str) -> bool:
        return self._subscribed is None or symbol in self._subscribed

    async def stream(self) -> AsyncIterator[Bar]:
        while self._pos < len(self._bars):
            if self._stopped:
                return
            bar = self._bars[self._pos]
            if not self._wanted(bar.symbol):
                self._pos += 1
                continue
            if (
                self._fail_after is not None
                and not self._failed
                and (self._yielded >= self._fail_after)
            ):
                self._failed = True
                self._state = ProviderState.DISCONNECTED
                self._last_error = f"simulated failure after {self._yielded} bars"
                raise ConnectionError(self._last_error)
            if self._speed > 0 and self._last_ts is not None:
                gap = (bar.timestamp - self._last_ts).total_seconds()
                if gap > 0:
                    await self._sleep(gap / self._speed)
                    if self._stopped:
                        return
            self._pos += 1  # advance before yield: delivered bars are never repeated
            self._last_ts = bar.timestamp
            self._yielded += 1
            self._last_message_at = bar.timestamp
            yield bar.model_copy(
                update={"source": ProviderName.REPLAY, "received_at": bar.timestamp}
            )
        self._finished = True

    def health(self) -> ProviderHealth:
        subscribed = (
            list(self._all_symbols) if self._subscribed is None else sorted(self._subscribed)
        )
        return ProviderHealth(
            provider=self.name,
            state=self._state,
            configured=True,
            mode=DataMode.REPLAY,
            last_message_at=self._last_message_at,
            last_error=self._last_error,
            reconnect_attempts=self._reconnects,
            subscribed_symbols=subscribed,
            messages_received=self._yielded,
        )
