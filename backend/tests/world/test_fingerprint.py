from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.world.fingerprint import (
    EventKey,
    entity_keys,
    event_fingerprint,
    is_same_event,
    text_similarity,
    text_tokens,
)
from app.world.settings import DedupConfig
from app.world.types import EventClass, GeoInfo, NormalizedEntity

D = DedupConfig()
T0 = datetime(2026, 9, 16, 10, 0, tzinfo=UTC)


def ent(name: str, kind: str = "country") -> NormalizedEntity:
    return NormalizedEntity(canonical=name, kind=kind, raw=name)


TW = [ent("Taiwan")]
GEO_TW = GeoInfo(country="TW", country_name="Taiwan", resolved=True)


def key(
    cls: EventClass,
    headline: str,
    entities: list[NormalizedEntity],
    geo: GeoInfo,
    at: datetime,
) -> EventKey:
    from app.world.fingerprint import geo_location_key

    return EventKey(cls, entity_keys(entities), geo_location_key(geo), at, text_tokens(headline))


def quake(headline: str, at: datetime = T0) -> EventKey:
    return key(EventClass.NATURAL_DISASTER, headline, TW, GEO_TW, at)


def test_fingerprint_deterministic_and_order_insensitive():
    e1 = [ent("Taiwan"), ent("TSMC", "company"), ent("crude oil", "commodity")]
    f1 = event_fingerprint(EventClass.NATURAL_DISASTER, e1, GEO_TW, T0, D)
    f2 = event_fingerprint(EventClass.NATURAL_DISASTER, list(reversed(e1)), GEO_TW, T0, D)
    assert f1 == f2 and len(f1) == 40
    # commodity is not a fingerprint entity kind; casefolding applied
    e2 = [ent("TAIWAN"), ent("tsmc", "company")]
    assert event_fingerprint(EventClass.NATURAL_DISASTER, e2, GEO_TW, T0, D) == f1
    assert event_fingerprint(EventClass.NATURAL_DISASTER, e1, GEO_TW, T0, D) == f1


def test_fingerprint_varies_by_class_entity_location_bucket():
    base = event_fingerprint(EventClass.NATURAL_DISASTER, TW, GEO_TW, T0, D)
    assert base != event_fingerprint(EventClass.CYBER_INCIDENT, TW, GEO_TW, T0, D)
    assert base != event_fingerprint(EventClass.NATURAL_DISASTER, [ent("Japan")], GEO_TW, T0, D)
    assert base != event_fingerprint(
        EventClass.NATURAL_DISASTER, TW, GeoInfo(country="JP", resolved=True), T0, D
    )
    assert base != event_fingerprint(
        EventClass.NATURAL_DISASTER, TW, GEO_TW, T0 + timedelta(hours=7), D
    )
    # same bucket (06:00-12:00)
    assert base == event_fingerprint(
        EventClass.NATURAL_DISASTER, TW, GEO_TW, T0 + timedelta(hours=1), D
    )


def test_naive_datetime_treated_as_utc():
    naive = T0.replace(tzinfo=None)
    assert event_fingerprint(EventClass.OTHER, [], None, naive, D) == event_fingerprint(
        EventClass.OTHER, [], None, T0, D
    )


def test_tokens_basic_and_stemming():
    t = text_tokens("Strait of Hormuz: 3 tankers seized, shipping halted!")
    assert {"strait", "hormuz", "tanker", "seiz", "halt"} <= t
    assert "of" not in t and "3" not in t
    assert text_tokens("Sanctions imposed") == text_tokens("sanction imposes")
    assert text_tokens("Port closed") == text_tokens("port closing")
    assert text_tokens("Iran's ports") == text_tokens("Iran port")


def test_tokens_empty_and_numbers_only():
    assert text_tokens("") == frozenset()
    assert text_tokens("   ... !!! 7.4 12") == frozenset()
    assert text_tokens("The and of") == frozenset()


def test_similarity_bounds():
    a, b = text_tokens("quake hits taiwan"), text_tokens("taiwan quake hits chip plants")
    s = text_similarity(a, b)
    assert 0.0 <= s <= 1.0 and s == 1.0  # containment
    assert text_similarity(a, a) == 1.0
    assert text_similarity(frozenset(), a) == 0.0
    assert text_similarity(frozenset(), frozenset()) == 0.0
    assert text_similarity(a, text_tokens("wheat prices rally")) == 0.0


def test_exact_duplicate_same():
    a = quake("Magnitude 7.4 earthquake strikes Taiwan")
    same, score, reason = is_same_event(a, a, D)
    assert same and score == 1.0 and reason == "identical_fingerprint"


def test_same_event_different_wording_merges():
    a = quake("Magnitude 7.4 earthquake strikes eastern Taiwan", T0)
    b = quake("Strong earthquake strikes Taiwan, buildings damaged", T0 + timedelta(hours=2))
    same, score, reason = is_same_event(a, b, D)
    assert same, reason
    assert 0.55 <= score <= 1.0


def test_syndicated_headline_variants_merge():
    a = key(
        EventClass.SHIPPING_DISRUPTION,
        "Tankers rerouted as Strait of Hormuz transit halted",
        [ent("Strait of Hormuz", "infrastructure")],
        GeoInfo(chokepoint="Strait of Hormuz", resolved=True),
        T0,
    )
    b = key(
        EventClass.SHIPPING_DISRUPTION,
        "Strait of Hormuz transit halted, tanker rerouting begins",
        [ent("Strait of Hormuz", "infrastructure")],
        GeoInfo(chokepoint="Strait of Hormuz", resolved=True),
        T0 + timedelta(hours=1),
    )
    assert is_same_event(a, b, D)[0]


def test_aftershock_stays_distinct():
    a = quake("Magnitude 7.4 earthquake strikes Taiwan", T0)
    b = quake("Magnitude 6.1 aftershock strikes Taiwan", T0 + timedelta(hours=6))
    same, _, reason = is_same_event(a, b, D)
    assert not same and "aftershock" in reason
    # even inside the same bucket
    c = quake("Magnitude 6.1 aftershock strikes Taiwan", T0 + timedelta(hours=1))
    assert not is_same_event(a, c, D)[0]
    # both aftershock reports of the same aftershock still merge
    d = quake("Aftershock rattles Taiwan, magnitude 6.1", T0 + timedelta(hours=6, minutes=10))
    assert is_same_event(c, d, D)[0]


def test_second_and_new_distinguish():
    a = quake("Earthquake strikes Taiwan")
    assert not is_same_event(a, quake("Second earthquake strikes Taiwan"), D)[0]
    assert not is_same_event(a, quake("New earthquake strikes Taiwan"), D)[0]


def test_update_word_is_neutral():
    a = quake("Earthquake strikes Taiwan", T0)
    b = quake("UPDATE: Earthquake strikes Taiwan", T0 + timedelta(hours=1))
    assert is_same_event(a, b, D)[0]


def test_same_class_different_country_distinct():
    a = quake("Earthquake strikes coastal region", T0)
    b = key(
        EventClass.NATURAL_DISASTER,
        "Earthquake strikes coastal region",
        [ent("Japan")],
        GeoInfo(country="JP", resolved=True),
        T0,
    )
    same, _, reason = is_same_event(a, b, D)
    assert not same and reason == "no_entity_or_location_overlap"


def test_same_country_different_class_distinct():
    a = quake("Earthquake strikes Taiwan")
    b = key(EventClass.SANCTION, "Earthquake strikes Taiwan", TW, GEO_TW, T0 + timedelta(hours=1))
    same, _, reason = is_same_event(a, b, D)
    assert not same and reason == "class_mismatch"


def test_compatible_family_can_merge():
    ents = [ent("Port of Shanghai", "infrastructure")]
    geo = GeoInfo(country="CN", city="Shanghai", resolved=True)
    a = key(EventClass.SHIPPING_DISRUPTION, "Shanghai port congestion halts cargo", ents, geo, T0)
    b = key(
        EventClass.PORT_DISRUPTION,
        "Shanghai port congestion halts cargo",
        ents,
        geo,
        T0 + timedelta(hours=1),
    )
    same, _, reason = is_same_event(a, b, D)
    assert same, reason
    # unrelated family stays apart
    c = key(EventClass.CYBER_INCIDENT, "Shanghai port congestion halts cargo", ents, geo, T0)
    assert not is_same_event(a, c, D)[0]


def test_far_apart_times_distinct():
    a = quake("Earthquake strikes Taiwan", T0)
    b = quake("Earthquake strikes Taiwan", T0 + timedelta(hours=37))
    same, _, reason = is_same_event(a, b, D)
    assert not same and reason.startswith("outside_merge_window")
    assert is_same_event(a, quake("Earthquake strikes Taiwan", T0 + timedelta(hours=36)), D)[0]


def test_bucket_boundary_merges_via_similarity():
    before = datetime(2026, 9, 16, 5, 55, tzinfo=UTC)
    after = datetime(2026, 9, 16, 6, 5, tzinfo=UTC)
    assert event_fingerprint(EventClass.NATURAL_DISASTER, TW, GEO_TW, before, D) != (
        event_fingerprint(EventClass.NATURAL_DISASTER, TW, GEO_TW, after, D)
    )
    a = quake("Powerful earthquake strikes Taiwan", before)
    b = quake("Taiwan struck by powerful earthquake", after)
    same, score, reason = is_same_event(a, b, D)
    assert same and reason.startswith("similar_text"), reason
    assert score >= D.text_similarity_threshold


def test_low_text_similarity_distinct():
    a = quake("Earthquake strikes Taiwan chip plants", T0)
    b = quake("Taiwan central bank holds rates steady", T0 + timedelta(hours=8))
    same, score, reason = is_same_event(a, b, D)
    assert not same and reason.startswith("text_similarity_below_threshold")
    assert 0.0 <= score < D.text_similarity_threshold


def test_empty_tokens_not_merged_unless_identical():
    a = quake("7.4", T0)
    b = quake("!!!", T0 + timedelta(hours=7))
    same, score, reason = is_same_event(a, b, D)
    assert not same and score == 0.0 and reason == "no_text_tokens"
    # identical fingerprint still counts as the same event
    assert is_same_event(a, quake("???", T0 + timedelta(hours=1)), D)[0]


def test_location_only_overlap_and_unknown_location():
    geo = GeoInfo(chokepoint="Suez Canal", resolved=True)
    a = key(EventClass.SHIPPING_DISRUPTION, "Suez Canal blocked by vessel", [], geo, T0)
    b = key(
        EventClass.SHIPPING_DISRUPTION,
        "Vessel blocks Suez Canal",
        [],
        geo,
        T0 + timedelta(hours=8),
    )
    assert is_same_event(a, b, D)[0]
    unk = GeoInfo()
    c = key(EventClass.SHIPPING_DISRUPTION, "Vessel blocks canal", [], unk, T0)
    d = key(EventClass.SHIPPING_DISRUPTION, "Vessel blocks canal", [], unk, T0 + timedelta(hours=8))
    assert not is_same_event(c, d, D)[0]


def test_is_same_event_deterministic_and_symmetric():
    a = quake("Earthquake strikes eastern Taiwan", T0)
    b = quake("Strong earthquake hits Taiwan", T0 + timedelta(hours=3))
    r1, r2, r3 = is_same_event(a, b, D), is_same_event(a, b, D), is_same_event(b, a, D)
    assert r1 == r2 == r3
