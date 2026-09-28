from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.world.providers.base import WorldEventProvider
from app.world.providers.replay import ReplayWorldEventProvider
from app.world.types import (
    RawWorldEvent,
    SourceRef,
    WorldMode,
    WorldProviderName,
    WorldProviderState,
)

T0 = datetime(2026, 9, 16, 9, 0, tzinfo=UTC)


def mk(eid: str | None, minute: int, headline: str = "Synthetic headline") -> RawWorldEvent:
    at = T0 + timedelta(minutes=minute)
    return RawWorldEvent(
        provider="replay",
        provider_event_id=eid,
        headline=headline,
        occurred_at=at,
        sources=[SourceRef(provider="replay", source_name="Mock Wire", retrieved_at=at)],
    )


def make_events() -> list[RawWorldEvent]:
    # deliberately shuffled; two share a timestamp
    return [mk("c", 5), mk("b", 0), mk("a", 0), mk("d", 10)]


async def collect(p: ReplayWorldEventProvider) -> list[RawWorldEvent]:
    return [e async for e in p.stream()]


def ids(events: list[RawWorldEvent]) -> list[str | None]:
    return [e.provider_event_id for e in events]


def test_is_world_event_provider() -> None:
    assert isinstance(ReplayWorldEventProvider([]), WorldEventProvider)


def test_rejects_bad_args() -> None:
    with pytest.raises(ValueError):
        ReplayWorldEventProvider([], speed=-1)
    with pytest.raises(ValueError):
        ReplayWorldEventProvider([], fail_after=-1)


async def test_order_is_deterministic() -> None:
    p = ReplayWorldEventProvider(make_events())
    assert ids(await collect(p)) == ["a", "b", "c", "d"]
    # input order irrelevant
    q = ReplayWorldEventProvider(list(reversed(make_events())))
    assert ids(await collect(q)) == ["a", "b", "c", "d"]


async def test_tie_break_by_id_then_headline_with_none_id() -> None:
    evs = [mk("x", 0, "B"), mk("x", 0, "A"), mk(None, 0, "Z")]
    out = await collect(ReplayWorldEventProvider(evs))
    assert [(e.provider_event_id, e.headline) for e in out] == [
        (None, "Z"),
        ("x", "A"),
        ("x", "B"),
    ]


async def test_emitted_copies_are_replay_and_inputs_untouched() -> None:
    evs = make_events()
    out = await collect(ReplayWorldEventProvider(evs))
    assert all(e.is_replay for e in out)
    assert all(not e.is_replay for e in evs)
    assert all(s.provider == "replay" for e in out for s in e.sources)
    by_id = {e.provider_event_id: e for e in evs}
    for e in out:
        assert e.sources == by_id[e.provider_event_id].sources


async def test_source_providers_preserved_as_given() -> None:
    at = T0
    raw = RawWorldEvent(
        provider="world_monitor",
        headline="x",
        occurred_at=at,
        sources=[SourceRef(provider="world_monitor", source_name="R", retrieved_at=at)],
    )
    (out,) = await collect(ReplayWorldEventProvider([raw]))
    assert out.is_replay is True
    assert out.sources[0].provider == "world_monitor"


async def test_lifecycle_and_health() -> None:
    p = ReplayWorldEventProvider(make_events())
    h = p.health()
    assert h.provider == WorldProviderName.REPLAY
    assert h.configured is True
    assert h.state == WorldProviderState.REPLAY
    assert h.mode == WorldMode.REPLAY
    assert h.events_received == 0
    assert h.last_event_at is None
    await p.connect()
    out = await collect(p)
    h = p.health()
    assert h.events_received == len(out) == 4
    assert h.last_event_at == T0 + timedelta(minutes=10)
    assert h.last_success_at == h.last_event_at
    assert h.state == WorldProviderState.REPLAY
    await p.disconnect()
    assert p.health().state == WorldProviderState.REPLAY


async def test_never_reports_live_mode() -> None:
    p = ReplayWorldEventProvider(make_events(), fail_after=1)
    seen = [p.health().mode]
    await p.connect()
    seen.append(p.health().mode)
    with pytest.raises(ConnectionError):
        await collect(p)
    seen.append(p.health().mode)
    await collect(p)
    seen.append(p.health().mode)
    await p.fetch_recent()
    await p.disconnect()
    seen.append(p.health().mode)
    assert set(seen) == {WorldMode.REPLAY}
    assert p.health().state == WorldProviderState.REPLAY


async def test_exhaustion_ends_stream() -> None:
    p = ReplayWorldEventProvider(make_events())
    assert not p.finished
    assert len(await collect(p)) == 4
    assert p.finished
    assert await collect(p) == []  # nothing more; does not hang or repeat


async def test_empty_stream_ends() -> None:
    assert await collect(ReplayWorldEventProvider([])) == []


async def test_fetch_recent_since() -> None:
    p = ReplayWorldEventProvider(make_events())
    assert ids(await p.fetch_recent()) == ["a", "b", "c", "d"]
    assert ids(await p.fetch_recent(T0)) == ["c", "d"]  # strictly greater
    assert ids(await p.fetch_recent(T0 + timedelta(minutes=5))) == ["d"]
    assert await p.fetch_recent(T0 + timedelta(minutes=10)) == []
    assert all(e.is_replay for e in await p.fetch_recent())


async def test_fetch_recent_does_not_move_stream_cursor() -> None:
    p = ReplayWorldEventProvider(make_events())
    await p.fetch_recent()
    assert ids(await collect(p)) == ["a", "b", "c", "d"]


async def test_speed_zero_never_sleeps() -> None:
    slept: list[float] = []

    async def fake_sleep(s: float) -> None:
        slept.append(s)

    await collect(ReplayWorldEventProvider(make_events(), speed=0.0, sleep=fake_sleep))
    assert slept == []


async def test_speed_sleeps_scaled_gaps_only_when_time_advances() -> None:
    slept: list[float] = []

    async def fake_sleep(s: float) -> None:
        slept.append(s)

    p = ReplayWorldEventProvider(make_events(), speed=60.0, sleep=fake_sleep)
    await collect(p)
    # a,b at +0 (no gap), c at +5min, d at +10min -> gaps 300s and 300s at speed 60
    assert slept == [5.0, 5.0]


async def test_disconnect_ends_stream_early() -> None:
    p = ReplayWorldEventProvider(make_events())
    got: list[str | None] = []
    async for e in p.stream():
        got.append(e.provider_event_id)
        if len(got) == 2:
            await p.disconnect()
    assert got == ["a", "b"]
    assert not p.finished
    # reconnect resumes without repeats
    await p.connect()
    assert ids(await collect(p)) == ["c", "d"]
    assert p.finished


async def test_disconnect_during_sleep_ends_stream() -> None:
    p: ReplayWorldEventProvider

    async def sleep_then_disconnect(_: float) -> None:
        await p.disconnect()

    p = ReplayWorldEventProvider(make_events(), speed=1.0, sleep=sleep_then_disconnect)
    assert ids(await collect(p)) == ["a", "b"]


async def test_fail_after_raises_once_then_resumes_without_repeat_or_skip() -> None:
    p = ReplayWorldEventProvider(make_events(), fail_after=2)
    got: list[str | None] = []
    with pytest.raises(ConnectionError):
        async for e in p.stream():
            got.append(e.provider_event_id)
    assert got == ["a", "b"]
    h = p.health()
    assert h.last_error is not None and "simulated" in h.last_error
    assert h.events_received == 2
    await p.connect()
    assert p.health().last_error is None
    got += ids(await collect(p))
    assert got == ["a", "b", "c", "d"]
    assert p.finished
    assert p.health().events_received == 4


async def test_fail_after_zero_fails_immediately_once() -> None:
    p = ReplayWorldEventProvider(make_events(), fail_after=0)
    with pytest.raises(ConnectionError):
        await collect(p)
    assert ids(await collect(p)) == ["a", "b", "c", "d"]
