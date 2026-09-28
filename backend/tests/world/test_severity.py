"""Pure tests for scoring/severity.py."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.world.scoring.severity import CLASS_BASE, score_severity, severity_bucket
from app.world.settings import SeverityConfig
from app.world.types import EventClass, GeoInfo, NormalizedEntity, RawWorldEvent

CFG = SeverityConfig()
T0 = datetime(2026, 9, 16, 9, 0, tzinfo=UTC)


def raw(headline: str = "Something happened", **kw) -> RawWorldEvent:
    return RawWorldEvent(provider="replay", headline=headline, occurred_at=T0, **kw)


def ent(name: str, kind: str) -> NormalizedEntity:
    return NormalizedEntity(canonical=name, kind=kind, raw=name)


def sev(cls=EventClass.NATURAL_DISASTER, entities=(), geo=None, r=None, cfg=CFG) -> float:
    return score_severity(cls, list(entities), geo or GeoInfo(), r or raw(), cfg)[0]


def test_class_base_table_documented_values():
    assert CLASS_BASE[EventClass.MILITARY_CONFLICT] == 0.70
    assert CLASS_BASE[EventClass.OTHER] == 0.15
    assert set(CLASS_BASE) == set(EventClass)


def test_no_bonuses_equals_class_base():
    for cls, base in CLASS_BASE.items():
        assert sev(cls) == pytest.approx(base)


def test_class_ordering():
    order = [
        EventClass.MILITARY_CONFLICT,
        EventClass.ENERGY_SUPPLY_DISRUPTION,
        EventClass.SHIPPING_DISRUPTION,
        EventClass.SANCTION,
        EventClass.CYBER_INCIDENT,
        EventClass.MACRO_EVENT,
        EventClass.OTHER,
    ]
    scores = [sev(c) for c in order]
    assert scores == sorted(scores, reverse=True)
    assert len(set(scores)) == len(scores)


def test_monotone_with_magnitude():
    prev = -1.0
    for m in [5.0, 6.0, 6.3, 6.6, 7.0, 7.5, 9.0]:
        s = sev(r=raw(magnitude={"richter": m}))
        assert s >= prev
        prev = s
    assert sev(r=raw(magnitude={"richter": 7.4})) > sev(r=raw(magnitude={"richter": 5.0}))
    assert sev(r=raw(magnitude={"richter": 7.0})) == sev(r=raw(magnitude={"richter": 8.5}))
    assert sev(r=raw(magnitude={"magnitude": 7.0})) == sev(r=raw(magnitude={"richter": 7.0}))


def test_casualties_and_outage_hours_raise_severity():
    base = sev(EventClass.INFRASTRUCTURE_OUTAGE)
    assert sev(EventClass.INFRASTRUCTURE_OUTAGE, r=raw(magnitude={"outage_hours": 24})) > base
    assert sev(EventClass.MILITARY_CONFLICT, r=raw(magnitude={"casualties": 500})) > sev(
        EventClass.MILITARY_CONFLICT
    )
    lo = sev(EventClass.INFRASTRUCTURE_OUTAGE, r=raw(magnitude={"outage_hours": 6}))
    hi = sev(EventClass.INFRASTRUCTURE_OUTAGE, r=raw(magnitude={"outage_hours": 40}))
    assert hi > lo


def test_natural_disaster_is_magnitude_driven():
    quake = sev(r=raw(magnitude={"richter": 7.5}))
    other = sev(EventClass.CYBER_INCIDENT, r=raw(magnitude={"richter": 7.5}))
    assert quake - CLASS_BASE[EventClass.NATURAL_DISASTER] > (
        other - CLASS_BASE[EventClass.CYBER_INCIDENT]
    )


def test_chokepoint_beats_non_chokepoint():
    cls = EventClass.SHIPPING_DISRUPTION
    plain = sev(cls, geo=GeoInfo(country="IR", resolved=True))
    choke = sev(cls, geo=GeoInfo(chokepoint="Strait of Hormuz", resolved=True))
    assert choke > plain


def test_multi_country_scope_and_infrastructure_bonus():
    cls = EventClass.SANCTION
    one = sev(cls, [ent("Russia", "country")])
    two = sev(cls, [ent("Russia", "country"), ent("Germany", "country")])
    assert two > one
    dup = sev(cls, [ent("Russia", "country"), ent("Russia", "country")])
    assert dup == one
    infra = sev(cls, [ent("Suez Canal", "infrastructure")])
    assert infra > sev(cls)


def test_provider_importance_blend():
    hi = sev(r=raw(provider_scores={"importance": 1.0}))
    lo = sev(r=raw(provider_scores={"importance": 0.0}))
    none = sev()
    assert lo < none < hi
    # w = 0.10 convex blend
    assert hi == pytest.approx(0.9 * none + 0.1 * 1.0)
    # 0..100 scale normalized
    assert sev(r=raw(provider_scores={"importance": 100})) == pytest.approx(hi)
    zero_w = SeverityConfig(provider_importance_weight=0.0)
    assert sev(r=raw(provider_scores={"importance": 1.0}), cfg=zero_w) == pytest.approx(none)


def test_missing_inputs_ok():
    s, comp = score_severity(EventClass.OTHER, [], GeoInfo(), raw(), CFG)
    assert 0.0 <= s <= 1.0
    assert comp["magnitude_key"] is None and comp["provider_importance"] is None
    # unknown magnitude keys / junk values are ignored
    s2 = sev(r=raw(magnitude={"foo": 5.0}, provider_scores={"other": 3.0}))
    assert s2 == pytest.approx(CLASS_BASE[EventClass.NATURAL_DISASTER])


def test_bounds_under_extreme_inputs():
    big = SeverityConfig(
        geo_scope_bonus=5.0,
        infrastructure_bonus=5.0,
        magnitude_bonus=5.0,
        provider_importance_weight=5.0,
    )
    entities = [
        ent("Iran", "country"),
        ent("Israel", "country"),
        ent("Strait of Hormuz", "infrastructure"),
    ]
    r = raw(
        magnitude={"richter": 1e12, "casualties": 1e15, "outage_hours": 1e9},
        provider_scores={"importance": 1e9},
    )
    for cls in EventClass:
        for cfg in (CFG, big):
            s = sev(cls, entities, GeoInfo(chokepoint="x"), r, cfg)
            assert 0.0 <= s <= 1.0
    neg = raw(magnitude={"richter": -50, "casualties": -5, "outage_hours": -1})
    assert 0.0 <= sev(r=neg) <= 1.0
    weird = SeverityConfig(
        geo_scope_bonus=-3.0,
        infrastructure_bonus=-3.0,
        magnitude_bonus=-3.0,
        provider_importance_weight=-1.0,
    )
    assert 0.0 <= sev(EventClass.MILITARY_CONFLICT, entities, cfg=weird) <= 1.0


def test_nan_inf_values_do_not_break():
    r = raw(
        magnitude={"richter": float("nan"), "casualties": float("inf")},
        provider_scores={"importance": float("nan")},
    )
    s = sev(r=r)
    assert s == pytest.approx(CLASS_BASE[EventClass.NATURAL_DISASTER])


def test_severity_is_not_sentiment():
    a = sev(EventClass.MILITARY_CONFLICT, r=raw("Border clash reported near port"))
    b = sev(EventClass.MILITARY_CONFLICT, r=raw("Great border clash reported near port"))
    c = sev(
        EventClass.MILITARY_CONFLICT,
        r=raw("Terrible border clash reported near port", body="great terrible awful wonderful"),
    )
    assert a == b == c


def test_duck_typed_entities():
    ents = [
        SimpleNamespace(canonical="Suez Canal", kind="infrastructure"),
        SimpleNamespace(canonical="Egypt", kind="country"),
    ]
    s = score_severity(EventClass.SHIPPING_DISRUPTION, ents, GeoInfo(), raw(), CFG)[0]
    assert s > CLASS_BASE[EventClass.SHIPPING_DISRUPTION]


def test_determinism_and_components():
    entities = [ent("Taiwan", "country"), ent("TSMC fabs", "infrastructure")]
    r = raw(magnitude={"richter": 7.4}, provider_scores={"importance": 0.8})
    first = score_severity(EventClass.NATURAL_DISASTER, entities, GeoInfo(), r, CFG)
    for _ in range(5):
        assert score_severity(EventClass.NATURAL_DISASTER, entities, GeoInfo(), r, CFG) == first
    score, comp = first
    assert comp["class_base"] == 0.45
    assert comp["magnitude_key"] == "richter"
    assert comp["infrastructure_entities"] == ["TSMC fabs"]
    assert comp["severity"] == score


@pytest.mark.parametrize(
    ("score", "bucket"),
    [
        (0.0, "LOW"),
        (0.2999, "LOW"),
        (0.30, "MODERATE"),
        (0.4999, "MODERATE"),
        (0.50, "ELEVATED"),
        (0.6999, "ELEVATED"),
        (0.70, "HIGH"),
        (1.0, "HIGH"),
    ],
)
def test_bucket_edges(score, bucket):
    assert severity_bucket(score) == bucket
