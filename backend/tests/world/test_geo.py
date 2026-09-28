"""Pure unit tests for app.world.geo (no DB/network)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.world.geo import (
    CHOKEPOINTS,
    country_display_names,
    location_key,
    normalize_geo,
)
from app.world.types import GeoInfo, NormalizedEntity, RawWorldEvent

T0 = datetime(2026, 9, 16, 9, 0, tzinfo=UTC)


def _raw(headline: str = "Something happened", **kw) -> RawWorldEvent:
    return RawWorldEvent(provider="replay", headline=headline, occurred_at=T0, **kw)


def _ent(canonical: str, kind: str) -> NormalizedEntity:
    return NormalizedEntity(canonical=canonical, kind=kind, raw=canonical)


def test_country_table_size():
    names = country_display_names()
    assert len(names) >= 60
    assert names["US"] == "United States"


@pytest.mark.parametrize(
    ("value", "iso", "name", "region"),
    [
        ("U.S.", "US", "United States", "North America"),
        ("usa", "US", "United States", "North America"),
        ("United States of America", "US", "United States", "North America"),
        ("UK", "GB", "United Kingdom", "Europe"),
        ("Türkiye", "TR", "Turkey", "Middle East"),
        ("Republic of Korea", "KR", "South Korea", "East Asia"),
        ("Korea, North", "KP", "North Korea", "East Asia"),
        ("uae", "AE", "United Arab Emirates", "Middle East"),
        ("  taiwan ", "TW", "Taiwan", "East Asia"),
        ("de", "DE", "Germany", "Europe"),  # ISO2 accepted for the raw country field
        ("IR", "IR", "Iran", "Middle East"),
        ("Burma", "MM", "Myanmar", "Southeast Asia"),
    ],
)
def test_country_alias(value, iso, name, region):
    g = normalize_geo(_raw(country=value), [])
    assert (g.country, g.country_name, g.region) == (iso, name, region)
    assert g.resolved is True
    assert g.chokepoint is None
    assert g.latitude is None and g.longitude is None
    assert location_key(g) == f"country:{iso.lower()}"


def test_country_from_entity_when_raw_missing():
    g = normalize_geo(_raw(), [_ent("Iran", "country")])
    assert g.country == "IR" and g.region == "Middle East" and g.resolved


def test_unrecognized_raw_country_falls_back_to_entity_else_unresolved():
    assert normalize_geo(_raw(country="Atlantis"), []).resolved is False
    g = normalize_geo(_raw(country="Atlantis"), [_ent("Japan", "country")])
    assert g.country == "JP"


def test_iso2_not_used_for_entities_or_text():
    # "in"/"it" as entity canonical must not become India/Italy
    g = normalize_geo(_raw("It is in the news"), [_ent("in", "country")])
    assert g.resolved is False


def test_upstream_coords_preserved_exactly():
    g = normalize_geo(_raw(country="Japan", latitude=35.123456789, longitude=139.987654321), [])
    assert g.latitude == 35.123456789 and g.longitude == 139.987654321
    assert g.resolved


def test_upstream_coords_only_resolve():
    g = normalize_geo(_raw(latitude=0.0, longitude=0.0), [])
    assert g.resolved and g.latitude == 0.0 and g.longitude == 0.0
    assert g.country is None and g.region is None
    assert location_key(g) == "unknown"


def test_upstream_coords_beat_chokepoint_coords():
    g = normalize_geo(
        _raw("Tanker hit near the Strait of Hormuz", latitude=25.0, longitude=55.0), []
    )
    assert (g.latitude, g.longitude) == (25.0, 55.0)
    assert g.chokepoint == "Strait of Hormuz"


def test_lone_latitude_ignored():
    g = normalize_geo(_raw(latitude=10.0), [])
    assert g.resolved is False and g.latitude is None


def test_chokepoint_fill_from_text():
    g = normalize_geo(_raw("Drone attack closes Strait of Hormuz to tankers"), [])
    assert g.chokepoint == "Strait of Hormuz"
    assert (g.latitude, g.longitude) == (26.57, 56.25)
    assert g.region == "Middle East"
    assert g.country is None and g.resolved
    assert location_key(g) == "chokepoint:strait-of-hormuz"


def test_chokepoint_fill_from_entity():
    g = normalize_geo(_raw("Shipping delays mount"), [_ent("Suez Canal", "infrastructure")])
    assert g.chokepoint == "Suez Canal"
    assert (g.latitude, g.longitude) == (30.46, 32.34)


def test_chokepoint_alias_and_body():
    g = normalize_geo(_raw("Houthi missile strike", body="Ships avoid Bab al-Mandab now."), [])
    assert g.chokepoint == "Bab el-Mandeb" and g.region == "Middle East"


def test_chokepoint_only_when_named():
    # 'Panama' alone / 'Malacca' alone / 'Suez' alone are not the chokepoints
    for text in ("Panama election held", "Malacca city fair", "Suez company earnings"):
        g = normalize_geo(_raw(text), [])
        assert g.chokepoint is None and g.latitude is None
    assert normalize_geo(_raw("Taiwan Strait transit"), []).chokepoint == "Taiwan Strait"


def test_chokepoint_word_boundary_and_case():
    assert normalize_geo(_raw("BOSPORUS closed"), []).chokepoint == "Bosphorus"
    assert normalize_geo(_raw("Hormuzabad festival"), []).chokepoint is None


def test_all_gazetteer_entries_valid():
    assert len(CHOKEPOINTS) >= 8
    for cp in CHOKEPOINTS:
        assert -90 <= cp.latitude <= 90 and -180 <= cp.longitude <= 180
        g = normalize_geo(_raw(f"Incident at {cp.name}"), [])
        assert g.chokepoint == cp.name
        assert (g.latitude, g.longitude, g.region) == (cp.latitude, cp.longitude, cp.region)


def test_unresolved():
    g = normalize_geo(_raw("Quarterly results beat estimates"), [_ent("NVIDIA", "company")])
    assert g == GeoInfo(resolved=False)
    assert g.country is None and g.region is None and g.city is None
    assert g.latitude is None and g.longitude is None and g.chokepoint is None
    assert location_key(g) == "unknown"


def test_conflicting_country_vs_chokepoint():
    g = normalize_geo(
        _raw("Tanker seized in Strait of Hormuz", country="Japan"),
        [_ent("Japan", "country"), _ent("Strait of Hormuz", "infrastructure")],
    )
    assert g.country == "JP" and g.country_name == "Japan"
    assert g.chokepoint == "Strait of Hormuz"
    assert location_key(g) == "chokepoint:strait-of-hormuz"
    # region stays from the resolved country; coords filled by the named chokepoint
    assert g.region == "East Asia"
    assert (g.latitude, g.longitude) == (26.57, 56.25)


def test_region_priority():
    # upstream region wins and is canonicalized
    assert normalize_geo(_raw(region="middle east", country="France"), []).region == "Middle East"
    # unknown upstream region preserved (not guessed)
    assert normalize_geo(_raw(region="Sahel"), []).region == "Sahel"
    # region entity fallback when no country
    g = normalize_geo(_raw(), [_ent("Middle East", "region")])
    assert g.region == "Middle East" and g.country is None
    assert location_key(g) == "region:middle-east"


def test_city_key_and_priority():
    g = normalize_geo(_raw(country="United States", city="New York"), [])
    assert g.city == "New York"
    assert location_key(g) == "city:us:new-york"
    g2 = normalize_geo(_raw(), [_ent("Shanghai", "city")])
    assert g2.city == "Shanghai" and location_key(g2) == "city:shanghai"


def test_location_key_priority_order():
    full = GeoInfo(
        country="TW",
        country_name="Taiwan",
        region="East Asia",
        city="Taipei",
        chokepoint="Taiwan Strait",
        resolved=True,
    )
    assert location_key(full) == "chokepoint:taiwan-strait"
    assert location_key(full.model_copy(update={"chokepoint": None})) == "city:tw:taipei"
    assert location_key(full.model_copy(update={"chokepoint": None, "city": None})) == "country:tw"
    assert location_key(GeoInfo(region="East Asia", resolved=True)) == "region:east-asia"
    assert location_key(GeoInfo()) == "unknown"


def test_location_key_stable_slug():
    a = GeoInfo(chokepoint="Bab al-Mandab", resolved=True)
    b = GeoInfo(chokepoint="Bab el-Mandeb", resolved=True)
    assert location_key(a) == location_key(b) == "chokepoint:bab-el-mandeb"
    assert location_key(GeoInfo(chokepoint="Some  Odd/Strait!", resolved=True)) == (
        "chokepoint:some-odd-strait"
    )
    assert location_key(GeoInfo(country_name="United States", resolved=True)) == "country:us"


@pytest.mark.parametrize(
    "kw",
    [{"latitude": 91.0}, {"latitude": -90.5}, {"longitude": 180.1}, {"longitude": -181.0}],
)
def test_invalid_coordinates_rejected_upstream(kw):
    with pytest.raises(ValidationError):
        _raw(**kw)


def test_deterministic_and_entity_duck_typing():
    class Ent:
        def __init__(self, canonical, kind):
            self.canonical, self.kind = canonical, kind

    raw = _raw("Blockade of Panama Canal", country="Panama")
    ents = [Ent("Panama", "country")]
    assert normalize_geo(raw, ents) == normalize_geo(raw, ents)
    g = normalize_geo(raw, ents)
    assert g.country == "PA" and g.chokepoint == "Panama Canal"
    assert (g.latitude, g.longitude) == (9.08, -79.68)
