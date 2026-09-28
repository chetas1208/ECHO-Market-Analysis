"""Deterministic replay world-event provider (no network). Emitted data is ALWAYS labelled REPLAY.

Determinism notes:
- Events are sorted once by (occurred_at, provider_event_id, headline); the cursor never moves
  backwards, so a reconnect after ``fail_after`` continues exactly where the stream stopped
  (no repeat, no skip).
- Emitted events are copies with ``is_replay=True`` forced. ``SourceRef`` objects (including
  their ``provider``) are preserved exactly as given; the input events are never mutated.
- ``health()`` always reports state REPLAY / mode REPLAY / configured True; it can never report
  LIVE. ``last_event_at`` / ``last_success_at`` use the event's own ``occurred_at`` (no wall clock)
  so replays are reproducible; ``last_error`` records a simulated failure.
- ``events_received`` counts events delivered via ``stream()`` and ``fetch_recent()``.
- ``fail_after`` is a one-shot failure simulation: after N events have been yielded by
  ``stream()`` (cumulative) it raises ``ConnectionError`` once, then resumes on the next call.
- ``speed`` > 0 sleeps ``gap_seconds / speed`` between consecutive yielded events with different
  ``occurred_at`` (``speed=0`` means as fast as possible, no sleeping).
- ``fetch_recent(since)`` is a pure snapshot: events with ``occurred_at > since`` (all when
  ``since`` is None); it does not move the stream cursor.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from datetime import datetime

from app.world.types import (
    RawWorldEvent,
    WorldMode,
    WorldProviderHealth,
    WorldProviderName,
    WorldProviderState,
)

SleepFn = Callable[[float], Awaitable[None]]


def _sort_key(e: RawWorldEvent) -> tuple[datetime, str, str]:
    return (e.occurred_at, e.provider_event_id or "", e.headline)


class ReplayWorldEventProvider:
    name: WorldProviderName = WorldProviderName.REPLAY

    def __init__(
        self,
        events: Sequence[RawWorldEvent],
        speed: float = 0.0,
        sleep: SleepFn = asyncio.sleep,
        fail_after: int | None = None,
    ) -> None:
        if speed < 0:
            raise ValueError("speed must be >= 0")
        if fail_after is not None and fail_after < 0:
            raise ValueError("fail_after must be >= 0")
        self._speed = speed
        self._sleep = sleep
        self._fail_after = fail_after
        self._events: list[RawWorldEvent] = sorted(events, key=_sort_key)
        self._pos = 0
        self._yielded = 0
        self._received = 0
        self._failed = False
        self._stopped = False
        self._finished = False
        self._last_ts: datetime | None = None
        self._last_event_at: datetime | None = None
        self._last_error: str | None = None

    @property
    def finished(self) -> bool:
        """True once the stream has reached the end of the data."""
        return self._finished

    @staticmethod
    def _emit(event: RawWorldEvent) -> RawWorldEvent:
        return event.model_copy(update={"is_replay": True})

    async def connect(self) -> None:
        self._stopped = False
        self._last_error = None

    async def disconnect(self) -> None:
        self._stopped = True

    async def fetch_recent(self, since: datetime | None = None) -> list[RawWorldEvent]:
        out = [self._emit(e) for e in self._events if since is None or e.occurred_at > since]
        if out:
            self._received += len(out)
            self._last_event_at = out[-1].occurred_at
        return out

    async def stream(self) -> AsyncIterator[RawWorldEvent]:
        while self._pos < len(self._events):
            if self._stopped:
                return
            event = self._events[self._pos]
            if (
                self._fail_after is not None
                and not self._failed
                and (self._yielded >= self._fail_after)
            ):
                self._failed = True
                self._last_error = f"simulated failure after {self._yielded} events"
                raise ConnectionError(self._last_error)
            if self._speed > 0 and self._last_ts is not None:
                gap = (event.occurred_at - self._last_ts).total_seconds()
                if gap > 0:
                    await self._sleep(gap / self._speed)
                    if self._stopped:
                        return
            self._pos += 1  # advance before yield: delivered events are never repeated
            self._last_ts = event.occurred_at
            self._yielded += 1
            self._received += 1
            self._last_event_at = event.occurred_at
            yield self._emit(event)
        self._finished = True

    def health(self) -> WorldProviderHealth:
        return WorldProviderHealth(
            provider=self.name,
            configured=True,
            state=WorldProviderState.REPLAY,
            mode=WorldMode.REPLAY,
            last_success_at=self._last_event_at,
            last_event_at=self._last_event_at,
            events_received=self._received,
            malformed_events=0,
            last_error=self._last_error,
        )
