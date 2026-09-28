"""Pure tests for world novelty scoring (no DB, no network)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.world.scoring.novelty import score_novelty
from app.world.settings import NoveltyConfig

CFG = NoveltyConfig()
NOW = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)


@dataclass(frozen=True)
class Key:
    event_class: str
    entity_keys: frozenset[str]
    location_key: str
    occurred_at: datetime
    tokens: frozenset[str]


def _key(
    *,
    cls: str = "shipping_disruption",
    entities: tuple[str, ...] = ("Strait of Hormuz", "Iran"),
    loc: str = "chokepoint:strait of hormuz",
    at: datetime = NOW,
    tokens: tuple[str, ...] = ("tanker", "traffic", "halted", "hormuz"),
) -> Key:
    return Key(cls, frozenset(entities), loc, at, frozenset(tokens))


def _ago(hours: float) -> datetime:
    return NOW - timedelta(hours=hours)


def test_first_report_is_fully_novel() -> None:
    score, comp = score_novelty(_key(), [], CFG, NOW)
    assert score == 1.0
    assert comp["nearest_similarity"] == 0.0
    assert comp["nearest_index"] is None
    assert comp["history_size"] == 0


def test_identical_repeat_within_hour_is_near_zero() -> None:
    score, comp = score_novelty(_key(), [_key(at=_ago(1))], CFG, NOW)
    assert score < 0.1
    assert comp["nearest_index"] == 0
    assert comp["history_size"] == 1
    assert abs(score - (1 - comp["nearest_similarity"])) < 1e-12


def test_same_topic_older_than_lookback_is_novel() -> None:
    old = _key(at=_ago(CFG.lookback_hours + 1))
    score, comp = score_novelty(_key(), [old], CFG, NOW)
    assert score == 1.0
    assert comp["nearest_index"] is None
    assert comp["history_size"] == 1
    assert comp["considered"] == 0


def test_unrelated_event_stays_high() -> None:
    other = _key(
        cls="cyber_incident",
        entities=("AWS", "United States"),
        loc="country:US",
        at=_ago(1),
        tokens=("cloud", "outage", "customers"),
    )
    score, _ = score_novelty(_key(), [other], CFG, NOW)
    assert score > 0.9


def test_aftershock_partial_overlap_is_intermediate() -> None:
    mainshock = _key(
        cls="natural_disaster",
        entities=("Taiwan", "TSMC"),
        loc="country:TW",
        at=_ago(6),
        tokens=("magnitude", "quake", "strikes", "taiwan"),
    )
    aftershock = _key(
        cls="natural_disaster",
        entities=("Taiwan",),
        loc="country:TW",
        at=NOW,
        tokens=("aftershock", "taiwan", "rattles"),
    )
    score, comp = score_novelty(aftershock, [mainshock], CFG, NOW)
    assert 0.2 < score < 0.8
    assert score < 1.0
    assert 0.0 < comp["nearest_similarity"] < 1.0


def test_monotone_in_time_decay() -> None:
    scores = [score_novelty(_key(), [_key(at=_ago(h))], CFG, NOW)[0] for h in (0.5, 6, 24, 48, 70)]
    assert scores == sorted(scores)
    assert scores[0] < scores[-1]


def test_shorter_decay_constant_raises_novelty() -> None:
    recent = [_key(at=_ago(12))]
    slow, _ = score_novelty(_key(), recent, NoveltyConfig(time_decay_hours=48.0), NOW)
    fast, _ = score_novelty(_key(), recent, NoveltyConfig(time_decay_hours=6.0), NOW)
    assert fast > slow


def test_nearest_index_points_at_most_similar() -> None:
    far = _key(cls="cyber_incident", entities=("AWS",), loc="country:US", tokens=("cloud",))
    near = _key(at=_ago(2))
    _, comp = score_novelty(_key(), [far, near, far], CFG, NOW)
    assert comp["nearest_index"] == 1
    assert comp["history_size"] == 3


def test_scores_bounded_including_empty_fields() -> None:
    empty = Key("other", frozenset(), "unknown", NOW, frozenset())
    for cand, recent in [
        (empty, [empty]),
        (_key(), [_key(at=_ago(0))]),
        (_key(), [empty, _key(at=_ago(3))]),
    ]:
        score, comp = score_novelty(cand, recent, CFG, NOW)
        assert 0.0 <= score <= 1.0
        assert 0.0 <= comp["nearest_similarity"] <= 1.0


def test_unknown_location_is_not_a_match() -> None:
    a = Key("other", frozenset(), "unknown", NOW, frozenset())
    b = Key("cyber_incident", frozenset(), "unknown", _ago(1), frozenset())
    score, comp = score_novelty(a, [b], CFG, NOW)
    assert score == 1.0
    assert comp["nearest_similarity"] == 0.0


def test_deterministic() -> None:
    recent = [_key(at=_ago(3)), _key(cls="sanction", at=_ago(9), tokens=("sanctions",))]
    assert score_novelty(_key(), recent, CFG, NOW) == score_novelty(_key(), recent, CFG, NOW)


def test_future_of_now_data_is_ignored() -> None:
    future = _key(at=NOW + timedelta(hours=1))
    score, comp = score_novelty(_key(), [future], CFG, NOW)
    assert score == 1.0
    assert comp["nearest_index"] is None
    assert comp["considered"] == 0
    # adding a future item never changes score or nearest match vs. past-only history
    past = [_key(at=_ago(5))]
    with_future = [*past, future]
    s1, c1 = score_novelty(_key(), past, CFG, NOW)
    s2, c2 = score_novelty(_key(), with_future, CFG, NOW)
    assert s1 == s2
    assert c1["nearest_index"] == c2["nearest_index"]
    assert c1["considered"] == c2["considered"] == 1
