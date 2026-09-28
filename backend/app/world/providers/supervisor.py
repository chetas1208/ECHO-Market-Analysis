"""Reconnecting wrapper around any ``WorldEventProvider``.

Behavior
- ``stream()`` yields events across provider failures. Any ``Exception`` from the inner provider
  (connect, stream iteration, factory) is absorbed: the supervisor records it, sleeps with
  exponential backoff + jitter (never below the backoff floor), rebuilds the inner provider via
  the factory, and continues. Only ``CancelledError`` ever escapes.
- ``WorldRateLimited`` (matched by class name, carries ``retry_after_s``): wait
  ``max(retry_after_s, backoff)``, state stays DEGRADED, ``retry_after_until`` is published.
- ``WorldProviderUnconfigured`` (class name) or inner health UNCONFIGURED: stop, no retry,
  health UNCONFIGURED.
- Backoff and the consecutive-failure counter reset after a success (an event yielded, or the
  inner provider reporting a newer ``last_success_at`` than the last failure).
- Staleness: no success for ``stale_after_s`` while HEALTHY -> STALE; cleared on next success.
  A REPLAY-mode inner provider is never marked stale (finite by design).
- A clean end of the inner stream (replay exhaustion / disconnect) ends the supervised stream.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta

from app.market.providers.backoff import Backoff
from app.market.settings import ReconnectConfig
from app.world.providers.base import WorldEventProvider
from app.world.types import (
    RawWorldEvent,
    WorldMode,
    WorldProviderHealth,
    WorldProviderName,
    WorldProviderState,
)

logger = logging.getLogger(__name__)

_Sleep = Callable[[float], Awaitable[object]]

_RATE_LIMITED = "WorldRateLimited"
_UNCONFIGURED = "WorldProviderUnconfigured"
_ERROR_AFTER_FAILURES = 5  # consecutive failures before DEGRADED escalates to ERROR
_MAX_RETRY_AFTER_S = 3600.0  # never obey an absurd upstream Retry-After beyond 1 h
_MAX_FLOOR_JITTER = 0.5  # floor = base_delay * (1 - min(jitter, this))

DEFAULT_RECONNECT = ReconnectConfig(base_delay_s=5.0, max_delay_s=300.0, factor=2.0, jitter=0.3)


def _has_class_name(exc: BaseException, name: str) -> bool:
    return any(c.__name__ == name for c in type(exc).__mro__)


def _retry_after(exc: BaseException) -> float | None:
    if not _has_class_name(exc, _RATE_LIMITED):
        return None
    raw = getattr(exc, "retry_after_s", None)
    try:
        val = float(raw) if raw is not None else 0.0
    except (TypeError, ValueError):
        val = 0.0
    if math.isnan(val) or val < 0:
        val = 0.0
    return min(val, _MAX_RETRY_AFTER_S)


class SupervisedWorldProvider:
    def __init__(
        self,
        factory: Callable[[], WorldEventProvider],
        *,
        reconnect: ReconnectConfig | None = None,
        stale_after_s: float = 5400.0,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        sleep: _Sleep = asyncio.sleep,
        backoff: Backoff | None = None,
    ) -> None:
        self._factory = factory
        self._cfg = reconnect if reconnect is not None else DEFAULT_RECONNECT
        self._stale_after_s = stale_after_s
        self._clock = clock
        self._sleep = sleep
        self._backoff = backoff if backoff is not None else Backoff(self._cfg)
        self._inner: WorldEventProvider | None = None
        self.name: WorldProviderName = WorldProviderName.WORLD_MONITOR
        self._state = WorldProviderState.CONNECTING
        self._connected = False
        self._needs_rebuild = False
        self._stopped = False
        self._consecutive_failures = 0
        self._total_failures = 0
        self._events = 0
        self._malformed_prev = 0
        self._last_error: str | None = None
        self._last_success_at: datetime | None = None
        self._last_event_at: datetime | None = None
        self._last_failure_at: datetime | None = None
        self._connected_at: datetime | None = None
        self._retry_delay: float | None = None
        self._retry_after_until: datetime | None = None
        self._recorded_sleeps: list[float] = []
        try:
            self._inner = factory()
            self.name = self._inner.name
        except Exception as exc:  # factory failure is retried by the stream loop
            self._record_failure(exc)

    # ------------------------------------------------------------------ public state

    @property
    def state(self) -> WorldProviderState:
        return self._state

    @property
    def consecutive_failures(self) -> int:
        return self._consecutive_failures

    @property
    def total_failures(self) -> int:
        return self._total_failures

    @property
    def events_received(self) -> int:
        return self._events

    def counters(self) -> dict[str, int]:
        return {
            "consecutive_failures": self._consecutive_failures,
            "total_failures": self._total_failures,
            "events_received": self._events,
        }

    def check_stale(self, now: datetime | None = None) -> bool:
        """Mark STALE when HEALTHY with no success for ``stale_after_s``; True if STALE."""
        now = now if now is not None else self._clock()
        if self._state not in (WorldProviderState.HEALTHY, WorldProviderState.STALE):
            return False
        if self._inner_mode() == WorldMode.REPLAY:
            return False
        ref = self._last_success_at or self._connected_at
        if ref is not None and (now - ref).total_seconds() >= self._stale_after_s:
            self._state = WorldProviderState.STALE
            return True
        if self._state == WorldProviderState.STALE:
            self._state = WorldProviderState.HEALTHY
        return False

    def health(self) -> WorldProviderHealth:
        inner = self._inner_health()
        self._absorb_inner_success(inner)
        self.check_stale()
        state = self._state
        mode = inner.mode if inner is not None else WorldMode.LIVE
        inner_states = (WorldProviderState.REPLAY, WorldProviderState.DEGRADED)
        if (
            state == WorldProviderState.HEALTHY
            and inner is not None
            and inner.state in inner_states
        ):
            state = inner.state
        if state == WorldProviderState.UNCONFIGURED or self._stopped:
            mode = WorldMode.OFFLINE
        inner_ok = inner.last_success_at if inner is not None else None
        inner_ev = inner.last_event_at if inner is not None else None
        retry_until = self._retry_after_until
        if retry_until is not None and retry_until <= self._clock():
            retry_until = None
        if retry_until is None and inner is not None:
            retry_until = inner.retry_after_until
        return WorldProviderHealth(
            provider=self.name,
            configured=state != WorldProviderState.UNCONFIGURED
            and (inner.configured if inner is not None else True),
            state=state,
            mode=mode,
            last_success_at=_latest(self._last_success_at, inner_ok),
            last_event_at=_latest(self._last_event_at, inner_ev),
            events_received=self._events,
            malformed_events=self._malformed_prev + (inner.malformed_events if inner else 0),
            last_error=self._last_error or (inner.last_error if inner else None),
            poll_interval_s=inner.poll_interval_s if inner is not None else None,
            retry_after_until=retry_until,
        )

    # ------------------------------------------------------------------ provider interface

    async def connect(self) -> None:
        """Try one connect. Never raises: failures are recorded and retried by ``stream()``."""
        self._stopped = False
        if self._state == WorldProviderState.UNCONFIGURED or self._connected:
            return
        await self._open()

    async def disconnect(self) -> None:
        await self.stop()

    async def stop(self) -> None:
        self._stopped = True
        self._connected = False
        await self._safe_disconnect()

    async def fetch_recent(self, since: datetime | None = None) -> list[RawWorldEvent]:
        """One supervised poll: failures are recorded and yield ``[]`` (never raises)."""
        if self._state == WorldProviderState.UNCONFIGURED:
            return []
        if not self._connected and not await self._open():
            return []
        assert self._inner is not None
        try:
            events = await self._inner.fetch_recent(since)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._fail(exc)
            self._connected = False
            await self._safe_disconnect()
            return []
        self._on_success(bool(events))
        self._events += len(events)
        return list(events)

    async def stream(self) -> AsyncIterator[RawWorldEvent]:
        """Yield events across failures. Ends on inner EOF, stop(), or UNCONFIGURED."""
        self._stopped = False
        it: AsyncIterator[RawWorldEvent] | None = None
        try:
            while not self._stopped and self._state != WorldProviderState.UNCONFIGURED:
                if self._retry_delay is not None:
                    delay, self._retry_delay = self._retry_delay, None
                    self._recorded_sleeps.append(delay)
                    await self._sleep(delay)
                    if self._stopped:
                        break
                if not self._connected and not await self._open():
                    continue
                assert self._inner is not None
                try:
                    it = self._inner.stream()
                    async for event in it:
                        self._on_success(True)
                        self._events += 1
                        yield event
                        if self._stopped:
                            return
                    return  # clean EOF (replay exhausted / provider disconnected)
                except Exception as exc:
                    if self._stopped:
                        return
                    if self._inner_unconfigured() or _has_class_name(exc, _UNCONFIGURED):
                        self._mark_unconfigured()
                        return
                    self._fail(exc)
                    self._connected = False
                    await self._safe_disconnect()
                finally:
                    await _aclose(it)
                    it = None
        except asyncio.CancelledError:
            await self._safe_disconnect()
            raise

    # ------------------------------------------------------------------ internals

    @property
    def recorded_sleeps(self) -> list[float]:
        """Delays requested from ``sleep`` so far (audit aid: proves no hammering)."""
        return list(self._recorded_sleeps)

    def _floor(self) -> float:
        return self._cfg.base_delay_s * (1.0 - min(abs(self._cfg.jitter), _MAX_FLOOR_JITTER))

    def _inner_health(self) -> WorldProviderHealth | None:
        if self._inner is None:
            return None
        try:
            return self._inner.health()
        except Exception:
            return None

    def _inner_mode(self) -> WorldMode | None:
        h = self._inner_health()
        return h.mode if h is not None else None

    def _inner_unconfigured(self) -> bool:
        h = self._inner_health()
        return h is not None and h.state == WorldProviderState.UNCONFIGURED

    def _absorb_inner_success(self, inner: WorldProviderHealth | None) -> None:
        """A poll that succeeded but produced no events still counts as a success."""
        ok = inner.last_success_at if inner is not None else None
        if ok is None:
            return
        if self._last_success_at is not None and ok <= self._last_success_at:
            return
        if self._last_failure_at is not None and ok < self._last_failure_at:
            return
        if self._state in (WorldProviderState.UNCONFIGURED,) or self._stopped:
            return
        self._mark_success(ok)

    def _on_success(self, produced_events: bool) -> None:
        now = self._clock()
        self._mark_success(now)
        if produced_events:
            self._last_event_at = now

    def _mark_success(self, at: datetime) -> None:
        self._last_success_at = at
        self._retry_after_until = None
        if self._consecutive_failures:
            self._consecutive_failures = 0
            self._backoff.reset()
        if self._state != WorldProviderState.UNCONFIGURED:
            self._state = WorldProviderState.HEALTHY

    def _fail(self, exc: BaseException) -> None:
        self._absorb_inner_success(self._inner_health())
        self._record_failure(exc)
        delay = self._backoff.next()
        delay = max(delay, self._floor())
        retry_after = _retry_after(exc)
        if retry_after is not None:
            delay = max(delay, retry_after)
            self._state = WorldProviderState.DEGRADED
            self._retry_after_until = self._clock() + timedelta(seconds=delay)
        elif self._consecutive_failures >= _ERROR_AFTER_FAILURES:
            self._state = WorldProviderState.ERROR
        else:
            self._state = WorldProviderState.DEGRADED
        self._retry_delay = delay
        logger.warning(
            "world provider %s failed (%s); retry #%d in %.2fs",
            self.name,
            self._last_error,
            self._consecutive_failures,
            delay,
        )

    def _retire_inner(self) -> None:
        h = self._inner_health()
        if h is not None:
            self._malformed_prev += h.malformed_events

    def _record_failure(self, exc: BaseException) -> None:
        self._needs_rebuild = True
        self._last_error = f"{type(exc).__name__}: {exc}"
        self._consecutive_failures += 1
        self._total_failures += 1
        self._last_failure_at = self._clock()

    async def _open(self) -> bool:
        """(Re)build the inner provider if needed and connect. True when connected."""
        try:
            if self._inner is None or self._needs_rebuild:
                self._retire_inner()
                self._inner = self._factory()
                self.name = self._inner.name
                self._needs_rebuild = False
            if self._inner_unconfigured():
                return self._mark_unconfigured()
            await self._inner.connect()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if _has_class_name(exc, _UNCONFIGURED) or self._inner_unconfigured():
                return self._mark_unconfigured()
            self._fail(exc)
            await self._safe_disconnect()
            return False
        self._connected = True
        self._connected_at = self._clock()
        if self._state == WorldProviderState.CONNECTING:
            self._state = WorldProviderState.HEALTHY
        return True

    def _mark_unconfigured(self) -> bool:
        self._state = WorldProviderState.UNCONFIGURED
        self._retry_delay = None
        self._retry_after_until = None
        self._connected = False
        logger.info("world provider %s unconfigured; supervisor will not retry", self.name)
        return False

    async def _safe_disconnect(self) -> None:
        if self._inner is None:
            return
        try:
            await self._inner.disconnect()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.debug("inner disconnect failed", exc_info=True)


def _latest(a: datetime | None, b: datetime | None) -> datetime | None:
    if a is None:
        return b
    if b is None:
        return a
    return max(a, b)


async def _aclose(it: object) -> None:
    aclose = getattr(it, "aclose", None)
    if aclose is not None:
        with contextlib.suppress(Exception):
            await aclose()
