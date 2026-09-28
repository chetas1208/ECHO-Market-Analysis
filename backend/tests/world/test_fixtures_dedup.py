"""Tests for the deterministic de-duplication scenarios (pure, no clock/DB/network)."""

from __future__ import annotations

import inspect
from datetime import timedelta

import pytest

from app.world import fixtures_dedup
from app.world.fixtures_dedup import SCENARIO_EXPECTATIONS, build_dedup_scenarios

KEYS = {"exact_duplicate", "independent_sources", "syndicated", "aftershock", "update"}
COUNTS = {
    "exact_duplicate": 2,
    "independent_sources": 4,
    "syndicated": 4,
    "aftershock": 2,
    "update": 2,
}


def test_keys_present() -> None:
    assert set(build_dedup_scenarios()) == KEYS
    assert set(SCENARIO_EXPECTATIONS) == KEYS


@pytest.mark.parametrize("key,count", COUNTS.items())
def test_event_counts(key: str, count: int) -> None:
    assert len(build_dedup_scenarios()[key]) == count


def test_all_replay_synthetic_and_aware() -> None:
    for events in build_dedup_scenarios().values():
        for ev in events:
            assert ev.is_replay is True
            assert ev.provider == "replay"
            assert ev.occurred_at.utcoffset() == timedelta(0)
            assert ev.sources
            for s in ev.sources:
                assert s.provider == "replay"
                assert s.source_name.startswith("Replay ")
                assert s.retrieved_at.utcoffset() == timedelta(0)
                assert s.published_at is not None and s.published_at.utcoffset() == timedelta(0)
                assert s.source_url is None or ".example.invalid/" in s.source_url


def test_timestamps_ordered() -> None:
    for key, events in build_dedup_scenarios().items():
        times = [e.occurred_at for e in events]
        assert times == sorted(times), key
        for ev in events:
            for s in ev.sources:
                assert s.retrieved_at >= s.published_at


def test_exact_duplicate_identical() -> None:
    a, b = build_dedup_scenarios()["exact_duplicate"]
    assert a is not b
    assert a.provider_event_id == b.provider_event_id
    assert a == b
    assert "Strait of Hormuz" in a.headline


def test_independent_sources() -> None:
    evs = build_dedup_scenarios()["independent_sources"]
    assert len({e.provider_event_id for e in evs}) == 4
    assert len({s.source_name for e in evs for s in e.sources}) == 4
    assert len({s.source_group for e in evs for s in e.sources}) == 4
    assert len({e.headline for e in evs}) == 4
    assert evs[-1].occurred_at - evs[0].occurred_at <= timedelta(minutes=90)
    assert all("Hormuz" in e.headline for e in evs)
    assert all(s.syndicated_from is None for e in evs for s in e.sources)


def test_syndicated_credits_original() -> None:
    evs = build_dedup_scenarios()["syndicated"]
    original, copies = evs[0], evs[1:]
    assert original.sources[0].source_group == "replay_wire_a"
    assert original.sources[0].syndicated_from is None
    assert len(copies) == 3
    assert len({e.provider_event_id for e in evs}) == 4
    for c in copies:
        src = c.sources[0]
        text = f"{c.headline} {c.body or ''}"
        assert src.syndicated_from == "replay_wire_a" or "(Replay Wire A)" in text
        assert src.source_group != "replay_wire_a"
    assert any(c.sources[0].syndicated_from == "replay_wire_a" for c in copies)
    assert any("(Replay Wire A)" in c.headline for c in copies)


def test_aftershock_distinct() -> None:
    main, after = build_dedup_scenarios()["aftershock"]
    assert main.occurred_at.isoformat() == "2026-09-16T10:00:00+00:00"
    assert after.occurred_at.isoformat() == "2026-09-16T16:00:00+00:00"
    assert main.magnitude == {"richter": 7.4}
    assert after.magnitude == {"richter": 6.1}
    assert "aftershock" in after.headline.lower()
    assert "aftershock" not in main.headline.lower()
    assert main.provider_event_id != after.provider_event_id
    assert main.country == after.country == "Taiwan"


def test_update_adds_information() -> None:
    first, later = build_dedup_scenarios()["update"]
    assert first.occurred_at.isoformat() == "2026-09-16T09:00:00+00:00"
    assert later.occurred_at.isoformat() == "2026-09-16T11:30:00+00:00"
    assert first.magnitude == {} and first.provider_scores == {}
    assert later.magnitude == {"richter": 7.4}
    assert later.provider_scores.get("importance") is not None
    assert first.provider_event_id != later.provider_event_id
    assert first.sources[0].source_group != later.sources[0].source_group
    assert first.country == later.country


def test_expectations_self_consistent() -> None:
    scenarios = build_dedup_scenarios()
    for key, exp in SCENARIO_EXPECTATIONS.items():
        n_events = len(scenarios[key])
        assert 1 <= exp["canonical_events"] <= n_events
        assert exp["min_sources"] <= exp["sources"]
        assert exp["sources"] <= sum(len(e.sources) for e in scenarios[key])
        assert exp["min_independent"] <= exp["independent"] <= exp["sources"]
        assert exp["independent"] + exp["syndicated"] <= exp["sources"]
        assert exp["independent"] >= exp["canonical_events"]
        assert exp["min_independent"] >= 1
    assert SCENARIO_EXPECTATIONS["exact_duplicate"]["sources"] == 1
    assert SCENARIO_EXPECTATIONS["independent_sources"]["independent"] == 4
    assert SCENARIO_EXPECTATIONS["syndicated"]["independent"] == 1
    assert SCENARIO_EXPECTATIONS["syndicated"]["syndicated"] == 3
    assert SCENARIO_EXPECTATIONS["aftershock"]["canonical_events"] == 2
    assert SCENARIO_EXPECTATIONS["update"]["independent"] == 2


def test_deterministic_and_fresh_objects() -> None:
    a, b = build_dedup_scenarios(), build_dedup_scenarios()
    assert a == b
    assert a["aftershock"][0] is not b["aftershock"][0]
    a["update"][0].headline = "mutated"
    assert build_dedup_scenarios()["update"][0].headline != "mutated"


def test_no_clock_or_random_use() -> None:
    src = inspect.getsource(fixtures_dedup)
    for banned in ("now(", "utcnow", "today(", "time.time", "import random", "uuid"):
        assert banned not in src
