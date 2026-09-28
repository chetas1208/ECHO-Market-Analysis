"""Pure tests for SupervisedWorldProvider (fake providers, fake clock, recorded sleeps)."""

from __future__ import annotations

import asyncio
import random
from datetime import UTC, datetime, timedelta

import pytest

from app.market.providers.backoff import Backoff
from app.market.settings import ReconnectConfig
from app.world.providers.supervisor import SupervisedWorldProvider
from app.world.types import (
    RawWorldEvent,
    WorldMode,
    WorldProviderHealth,
    WorldProviderName,
    WorldProviderState,
)

T0 = datetime(2026, 9, 16, 9, 0, tzinfo=UTC)
CFG = ReconnectConfig(base_delay_s=1.0, max_delay_s=60.0, factor=2.0, jitter=0.0)


class WorldRateLimited(Exception):  # matched by class name, like the real adapter's error
    def __init__(self, retry_after_s: float) -> None:
        super().__init__(f"rate limited, retry after {retry_after_s}")
        self.retry_after_s = retry_after_s


class WorldProviderUnconfigured(Exception):
    pass


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class Sleeper:
    def __init__(self, clock: Clock | None = None) -> None:
        self.calls: list[float] = []
        self._clock = clock

    async def __call__(self, delay: float) -> None:
        self.calls.append(delay)
        if self._clock is not None:
            self._clock.advance(delay)
        await asyncio.sleep(0)


def ev(n: int = 1) -> RawWorldEvent:
    return RawWorldEvent(
        provider="world_monitor",
        provider_event_id=f"e{n}",
        headline=f"Synthetic event {n}",
        occurred_at=T0,
    )


class FakeInner:
    """Scripted provider: script items are events (yielded) or exceptions (raised)."""

    def __init__(
        self,
        script: list[object] | None = None,
        *,
        connect_exc: Exception | None = None,
        state: WorldProviderState = WorldProviderState.HEALTHY,
        mode: WorldMode = WorldMode.LIVE,
        block_after: bool = False,
    ) -> None:
        self.name = WorldProviderName.WORLD_MONITOR
        self.script = list(script or [])
        self.connect_exc = connect_exc
        self.state = state
        self.mode = mode
        self.block_after = block_after
        self.connects = 0
        self.disconnects = 0
        self.malformed = 0
        self.last_success_at: datetime | None = None
        self.fetch_result: list[RawWorldEvent] | Exception = []

    async def connect(self) -> None:
        self.connects += 1
        if self.connect_exc is not None:
            raise self.connect_exc

    async def disconnect(self) -> None:
        self.disconnects += 1

    async def fetch_recent(self, since: datetime | None = None) -> list[RawWorldEvent]:
        if isinstance(self.fetch_result, Exception):
            raise self.fetch_result
        return self.fetch_result

    async def stream(self):
        for item in self.script:
            if isinstance(item, BaseException):
                raise item
            yield item
            await asyncio.sleep(0)
        if self.block_after:
            await asyncio.Event().wait()

    def health(self) -> WorldProviderHealth:
        return WorldProviderHealth(
            provider=self.name,
            configured=self.state != WorldProviderState.UNCONFIGURED,
            state=self.state,
            mode=self.mode,
            last_success_at=self.last_success_at,
            malformed_events=self.malformed,
            poll_interval_s=30.0,
        )


class Factory:
    """Hands out scripted inners in order; after the list is exhausted, empty inners."""

    def __init__(self, inners: list[FakeInner]) -> None:
        self.inners = list(inners)
        self.built: list[FakeInner] = []

    def __call__(self) -> FakeInner:
        inner = self.inners.pop(0) if self.inners else FakeInner([])
        self.built.append(inner)
        return inner


def make(
    inners: list[FakeInner],
    *,
    cfg: ReconnectConfig = CFG,
    stale_after_s: float = 5400.0,
    backoff: Backoff | None = None,
) -> tuple[SupervisedWorldProvider, Factory, Sleeper, Clock]:
    clock = Clock()
    sleeper = Sleeper()
    factory = Factory(inners)
    sup = SupervisedWorldProvider(
        factory,
        reconnect=cfg,
        stale_after_s=stale_after_s,
        clock=clock,
        sleep=sleeper,
        backoff=backoff,
    )
    return sup, factory, sleeper, clock


async def collect(sup: SupervisedWorldProvider, limit: int = 1000) -> list[RawWorldEvent]:
    out: list[RawWorldEvent] = []
    async for e in sup.stream():
        out.append(e)
        if len(out) >= limit:
            break
    return out


# ------------------------------------------------------------------ reconnect / backoff


async def test_reconnects_after_failures_and_keeps_yielding() -> None:
    sup, factory, sleeper, _ = make(
        [
            FakeInner([ev(1), ConnectionError("reset")]),
            FakeInner([OSError("boom")]),
            FakeInner([TimeoutError("slow")]),
            FakeInner([ev(2), ev(3)]),
        ]
    )
    events = await collect(sup)
    assert [e.provider_event_id for e in events] == ["e1", "e2", "e3"]
    assert len(factory.built) == 4  # rebuilt via factory after every failure
    assert sup.total_failures == 3
    assert sup.consecutive_failures == 0  # reset by the successful events
    assert sup.state == WorldProviderState.HEALTHY
    assert len(sleeper.calls) == 3
    assert all(i.disconnects >= 1 for i in factory.built[:3])


async def test_connect_failure_is_absorbed_and_retried() -> None:
    sup, factory, sleeper, _ = make(
        [
            FakeInner(connect_exc=ConnectionError("no route")),
            FakeInner(connect_exc=RuntimeError("weird")),
            FakeInner([ev(1)]),
        ]
    )
    await sup.connect()  # must not raise
    assert sup.state == WorldProviderState.DEGRADED
    events = await collect(sup)
    assert [e.provider_event_id for e in events] == ["e1"]
    assert len(factory.built) == 3
    assert len(sleeper.calls) == 2


async def test_backoff_grows_and_resets_after_success() -> None:
    sup, _, sleeper, _ = make(
        [
            FakeInner([ConnectionError("1")]),
            FakeInner([ConnectionError("2")]),
            FakeInner([ConnectionError("3")]),
            FakeInner([ev(1), ConnectionError("4")]),  # success in between resets backoff
            FakeInner([ev(2)]),
        ]
    )
    events = await collect(sup)
    assert len(events) == 2
    assert sleeper.calls == [1.0, 2.0, 4.0, 1.0]


async def test_sleeps_never_below_backoff_floor_with_jitter() -> None:
    cfg = ReconnectConfig(base_delay_s=2.0, max_delay_s=30.0, factor=2.0, jitter=0.3)
    inners = [FakeInner([ConnectionError(str(i))]) for i in range(12)] + [FakeInner([ev(1)])]
    sup, _, sleeper, _ = make(inners, cfg=cfg, backoff=Backoff(cfg, random.Random(7)))
    await collect(sup)
    assert len(sleeper.calls) == 12
    for i, d in enumerate(sleeper.calls):
        floor = min(cfg.max_delay_s, cfg.base_delay_s * cfg.factor**i) * (1 - cfg.jitter)
        assert d >= floor - 1e-9, (i, d, floor)
        assert d >= cfg.base_delay_s * (1 - cfg.jitter)  # never hammers below the base floor


async def test_floor_enforced_even_with_degenerate_jitter() -> None:
    cfg = ReconnectConfig(base_delay_s=4.0, max_delay_s=30.0, factor=2.0, jitter=1.0)
    inners = [FakeInner([ConnectionError(str(i))]) for i in range(30)] + [FakeInner([ev(1)])]
    sup, _, sleeper, _ = make(inners, cfg=cfg, backoff=Backoff(cfg, random.Random(3)))
    await collect(sup)
    assert min(sleeper.calls) >= 2.0  # base * (1 - 0.5)


async def test_twenty_consecutive_failures_do_not_crash() -> None:
    kinds = [ConnectionError, OSError, TimeoutError, ValueError, RuntimeError]
    inners = [FakeInner([kinds[i % 5](f"f{i}")]) for i in range(20)] + [FakeInner([ev(1)])]
    sup, _, sleeper, _ = make(inners)
    seen_states: list[WorldProviderState] = []
    agen = sup.stream()
    first = await agen.__anext__()  # never raises to the consumer
    assert first.provider_event_id == "e1"
    assert len(sleeper.calls) == 20
    assert sleeper.calls[-1] == CFG.max_delay_s  # capped, not unbounded
    assert sup.total_failures == 20
    seen_states.append(sup.health().state)
    await agen.aclose()
    assert seen_states == [WorldProviderState.HEALTHY]


async def test_state_escalates_degraded_then_error_then_recovers() -> None:
    inners = [FakeInner([ConnectionError(str(i))]) for i in range(6)] + [FakeInner([ev(1)])]
    sup, _, _, _ = make(inners)
    states: list[WorldProviderState] = []
    real_sleep = sup._sleep

    async def spy(delay: float) -> None:
        states.append(sup.health().state)
        await real_sleep(delay)

    sup._sleep = spy
    await collect(sup)
    assert states[0] == WorldProviderState.DEGRADED
    assert states[-1] == WorldProviderState.ERROR
    assert sup.health().state == WorldProviderState.HEALTHY


class PollThenFail(FakeInner):
    """Completes a successful (empty) poll, then fails: no event is ever yielded."""

    def __init__(self, clock: Clock) -> None:
        super().__init__([])
        self._clock = clock

    async def stream(self):
        self.last_success_at = self._clock()
        raise ConnectionError("dropped after empty poll")
        yield  # pragma: no cover


async def test_poll_success_without_events_resets_backoff() -> None:
    clock = Clock()
    sleeper = Sleeper(clock)
    factory = Factory(
        [
            FakeInner([ConnectionError("a")]),
            PollThenFail(clock),
            PollThenFail(clock),
            FakeInner([ev(1)]),
        ]
    )
    sup = SupervisedWorldProvider(factory, reconnect=CFG, clock=clock, sleep=sleeper)
    await collect(sup)
    # every empty-but-successful poll restarts the backoff, so it never grows past base
    assert sleeper.calls == [1.0, 1.0, 1.0]


# ------------------------------------------------------------------ rate limit


async def test_retry_after_honored_and_state_degraded() -> None:
    sup, _, sleeper, clock = make(
        [FakeInner([WorldRateLimited(120.0)]), FakeInner([ev(1)])]  # backoff would be 1.0
    )
    agen = sup.stream()
    seen: list[WorldProviderState] = []
    real_sleep = sup._sleep

    async def spy(delay: float) -> None:
        h = sup.health()
        seen.append(h.state)
        assert h.retry_after_until == clock() + timedelta(seconds=120.0)
        await real_sleep(delay)

    sup._sleep = spy
    assert (await agen.__anext__()).provider_event_id == "e1"
    await agen.aclose()
    assert sleeper.calls == [120.0]
    assert seen == [WorldProviderState.DEGRADED]
    assert sup.health().retry_after_until is None  # cleared after success


async def test_retry_after_smaller_than_backoff_uses_backoff() -> None:
    inners = [FakeInner([ConnectionError(str(i))]) for i in range(3)]
    inners.append(FakeInner([WorldRateLimited(0.5)]))  # 4th failure: backoff = 8.0 > 0.5
    inners.append(FakeInner([ev(1)]))
    sup, _, sleeper, _ = make(inners)
    await collect(sup)
    assert sleeper.calls == [1.0, 2.0, 4.0, 8.0]


async def test_rate_limited_never_escalates_to_error() -> None:
    inners = [FakeInner([WorldRateLimited(1.0)]) for _ in range(8)] + [FakeInner([ev(1)])]
    sup, _, _, _ = make(inners)
    states: list[WorldProviderState] = []
    real = sup._sleep

    async def spy(delay: float) -> None:
        states.append(sup.health().state)
        await real(delay)

    sup._sleep = spy
    await collect(sup)
    assert set(states) == {WorldProviderState.DEGRADED}


# ------------------------------------------------------------------ unconfigured


async def test_unconfigured_exception_stops_without_retry() -> None:
    sup, factory, sleeper, _ = make([FakeInner([WorldProviderUnconfigured("no key")])])
    events = await collect(sup)
    assert events == []
    assert sleeper.calls == []
    assert len(factory.built) == 1
    h = sup.health()
    assert h.state == WorldProviderState.UNCONFIGURED
    assert h.configured is False
    assert h.mode == WorldMode.OFFLINE


async def test_inner_health_unconfigured_stops_without_retry() -> None:
    inner = FakeInner([ev(1)], state=WorldProviderState.UNCONFIGURED)
    sup, factory, sleeper, _ = make([inner])
    await sup.connect()
    assert await collect(sup) == []
    assert sleeper.calls == []
    assert inner.connects == 0
    assert len(factory.built) == 1
    assert sup.health().state == WorldProviderState.UNCONFIGURED


async def test_unconfigured_raised_on_connect_stops() -> None:
    sup, factory, sleeper, _ = make([FakeInner(connect_exc=WorldProviderUnconfigured("nokey"))])
    assert await collect(sup) == []
    assert sleeper.calls == []
    assert len(factory.built) == 1
    assert sup.state == WorldProviderState.UNCONFIGURED


# ------------------------------------------------------------------ stale


async def test_stale_marks_and_clears_on_next_success() -> None:
    sup, _, _, clock = make([FakeInner([ev(1), ev(2)])], stale_after_s=100.0)
    agen = sup.stream()
    await agen.__anext__()
    assert sup.health().state == WorldProviderState.HEALTHY
    clock.advance(99)
    assert sup.health().state == WorldProviderState.HEALTHY
    clock.advance(2)
    assert sup.health().state == WorldProviderState.STALE
    await agen.__anext__()  # next success clears it
    assert sup.health().state == WorldProviderState.HEALTHY
    await agen.aclose()


async def test_stale_counts_from_connect_when_no_event_yet() -> None:
    sup, _, _, clock = make([FakeInner([])], stale_after_s=100.0)
    await sup.connect()
    clock.advance(101)
    assert sup.health().state == WorldProviderState.STALE


async def test_inner_poll_success_keeps_supervisor_fresh_without_events() -> None:
    inner = FakeInner([])
    sup, _, _, clock = make([inner], stale_after_s=100.0)
    await sup.connect()
    clock.advance(150)
    inner.last_success_at = clock()  # empty-but-successful poll
    h = sup.health()
    assert h.state == WorldProviderState.HEALTHY
    assert h.last_success_at == clock()


async def test_replay_inner_never_stale() -> None:
    inner = FakeInner([], state=WorldProviderState.REPLAY, mode=WorldMode.REPLAY)
    sup, _, _, clock = make([inner], stale_after_s=10.0)
    await sup.connect()
    clock.advance(1000)
    h = sup.health()
    assert h.state == WorldProviderState.REPLAY
    assert h.mode == WorldMode.REPLAY


# ------------------------------------------------------------------ health merge


async def test_health_merges_inner_and_supervisor_state() -> None:
    inner = FakeInner([ev(1)])
    inner.malformed = 3
    sup, _, _, clock = make([inner])
    events = await collect(sup)
    assert len(events) == 1
    h = sup.health()
    assert h.provider == WorldProviderName.WORLD_MONITOR
    assert h.events_received == 1
    assert h.malformed_events == 3
    assert h.poll_interval_s == 30.0
    assert h.last_event_at == clock()
    assert h.state == WorldProviderState.HEALTHY
    assert sup.counters() == {
        "consecutive_failures": 0,
        "total_failures": 0,
        "events_received": 1,
    }


async def test_health_exposes_failure_counters_and_last_error() -> None:
    inners = [FakeInner([ConnectionError("dns down")]) for _ in range(3)] + [
        FakeInner([ev(1)], block_after=True)
    ]
    sup, _, _, _ = make(inners)
    agen = sup.stream()
    await agen.__anext__()
    h = sup.health()
    assert "ConnectionError: dns down" in (h.last_error or "")
    assert sup.total_failures == 3
    await agen.aclose()


async def test_malformed_counter_survives_rebuild() -> None:
    a = FakeInner([ConnectionError("x")])
    a.malformed = 2
    b = FakeInner([ev(1)])
    b.malformed = 1
    sup, _, _, _ = make([a, b])
    await collect(sup)
    assert sup.health().malformed_events == 3


async def test_factory_failure_is_absorbed() -> None:
    calls = {"n": 0}

    def factory() -> FakeInner:
        calls["n"] += 1
        if calls["n"] in (1, 2):
            raise RuntimeError("factory broke")
        return FakeInner([ev(1)])

    sleeper = Sleeper()
    sup = SupervisedWorldProvider(factory, reconnect=CFG, clock=Clock(), sleep=sleeper)
    events = await collect(sup)
    assert [e.provider_event_id for e in events] == ["e1"]
    assert sup.total_failures == 2


async def test_fetch_recent_never_raises() -> None:
    inner = FakeInner([])
    inner.fetch_result = ConnectionError("poll failed")
    sup, _, _, _ = make([inner, FakeInner([])])
    assert await sup.fetch_recent(None) == []
    assert sup.state == WorldProviderState.DEGRADED
    assert sup.total_failures == 1


# ------------------------------------------------------------------ stop / cancel


async def test_stop_ends_stream_and_disconnects() -> None:
    inner = FakeInner([ev(1), ev(2), ev(3)])
    sup, _, sleeper, _ = make([inner])
    out = []
    async for e in sup.stream():
        out.append(e)
        await sup.stop()
    assert len(out) == 1
    assert inner.disconnects >= 1
    assert sleeper.calls == []
    assert sup.health().mode == WorldMode.OFFLINE


async def test_cancel_during_stream_is_clean() -> None:
    inner = FakeInner([ev(1)], block_after=True)
    sup, _, _, _ = make([inner])
    got: list[RawWorldEvent] = []

    async def consume() -> None:
        async for e in sup.stream():
            got.append(e)

    task = asyncio.create_task(consume())
    for _ in range(20):
        await asyncio.sleep(0)
    assert len(got) == 1
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert inner.disconnects >= 1


async def test_cancel_during_backoff_sleep_is_clean() -> None:
    started = asyncio.Event()

    async def blocking_sleep(_delay: float) -> None:
        started.set()
        await asyncio.Event().wait()

    inner = FakeInner([ConnectionError("x")])
    factory = Factory([inner])
    sup = SupervisedWorldProvider(factory, reconnect=CFG, clock=Clock(), sleep=blocking_sleep)

    async def consume() -> None:
        async for _ in sup.stream():
            pass

    task = asyncio.create_task(consume())
    await asyncio.wait_for(started.wait(), 1.0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert inner.disconnects >= 1


async def test_clean_eof_ends_stream_without_retry() -> None:
    sup, factory, sleeper, _ = make([FakeInner([ev(1), ev(2)])])
    events = await collect(sup)
    assert len(events) == 2
    assert sleeper.calls == []
    assert len(factory.built) == 1
