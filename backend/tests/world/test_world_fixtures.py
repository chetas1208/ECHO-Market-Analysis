"""Pure tests for the deterministic world replay fixtures."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.world.fixtures import WORLD_FIXTURES, WorldFixture
from app.world.types import EventClass

CHANNELS = (
    "oil_supply",
    "natural_gas_supply",
    "energy_prices",
    "shipping_capacity",
    "shipping_costs",
    "port_capacity",
    "semiconductor_supply",
    "compute_supply",
    "commodity_supply",
    "commodity_prices",
    "consumer_demand",
    "industrial_demand",
    "interest_rates",
    "credit_conditions",
    "regulatory_risk",
    "geopolitical_risk",
    "cybersecurity_risk",
    "infrastructure_availability",
    "global_trade",
)

KEYS = {"hormuz", "taiwan_quake", "cloud_outage", "oil_infra", "cyber_incident", "sanction"}


def test_six_keys_present() -> None:
    assert set(WORLD_FIXTURES) == KEYS
    for key, fx in WORLD_FIXTURES.items():
        assert isinstance(fx, WorldFixture)
        assert fx.key == key


def test_all_replay_and_synthetic_sources() -> None:
    for fx in WORLD_FIXTURES.values():
        assert fx.raw.is_replay is True
        assert fx.raw.provider == "replay"
        assert fx.raw.sources, fx.key
        for s in fx.raw.sources:
            assert s.provider == "replay"
            assert s.source_name.startswith("Replay ")
            assert s.source_url is None or "example.invalid" in s.source_url


def test_timestamps_aware_and_ordered() -> None:
    for fx in WORLD_FIXTURES.values():
        assert fx.raw.occurred_at.tzinfo is not None
        assert fx.raw.occurred_at.utcoffset() == timedelta(0)
        for s in fx.raw.sources:
            assert s.retrieved_at.tzinfo is not None
            assert s.published_at is not None and s.published_at.tzinfo is not None
            assert s.retrieved_at >= s.published_at >= fx.raw.occurred_at
            assert s.retrieved_at - fx.raw.occurred_at <= timedelta(minutes=30)


def test_hormuz_spec() -> None:
    fx = WORLD_FIXTURES["hormuz"]
    assert fx.raw.provider_event_id == "replay-hormuz-001"
    assert fx.raw.headline == "Strait of Hormuz — Increased Naval Activity"
    assert fx.raw.occurred_at == datetime(2026, 9, 16, 9, 0, tzinfo=UTC)
    assert fx.expected_class is EventClass.SHIPPING_DISRUPTION
    assert fx.expected_channels == {
        "oil_supply": -1,
        "energy_prices": 1,
        "shipping_costs": 1,
        "global_trade": -1,
    }
    assert fx.expected_country is None
    assert fx.raw.region == "Middle East"
    assert len(fx.raw.sources) == 2


def test_taiwan_quake_spec() -> None:
    fx = WORLD_FIXTURES["taiwan_quake"]
    assert fx.raw.magnitude == {"richter": 7.4}
    assert fx.expected_class is EventClass.NATURAL_DISASTER
    assert fx.expected_channels == {"semiconductor_supply": -1}
    assert "Hualien" in fx.raw.headline


@pytest.mark.parametrize(
    ("key", "cls", "channels"),
    [
        ("cloud_outage", EventClass.INFRASTRUCTURE_OUTAGE, {"infrastructure_availability": -1}),
        ("oil_infra", EventClass.ENERGY_SUPPLY_DISRUPTION, {"oil_supply": -1, "energy_prices": 1}),
        ("cyber_incident", EventClass.CYBER_INCIDENT, {"cybersecurity_risk": 1}),
        ("sanction", EventClass.SANCTION, {"regulatory_risk": 1, "geopolitical_risk": 1}),
    ],
)
def test_expected_class_and_channels(key: str, cls: EventClass, channels: dict[str, int]) -> None:
    fx = WORLD_FIXTURES[key]
    assert fx.expected_class is cls
    assert fx.expected_channels == channels


def test_expected_fields_well_formed() -> None:
    for fx in WORLD_FIXTURES.values():
        assert isinstance(fx.expected_class, EventClass)
        assert fx.expected_channels, fx.key
        for ch, sign in fx.expected_channels.items():
            assert ch in CHANNELS, (fx.key, ch)
            assert sign in (-1, 1)
        if fx.expected_country is not None:
            assert len(fx.expected_country) == 2 and fx.expected_country.isupper()


def test_raw_content_plausible() -> None:
    for fx in WORLD_FIXTURES.values():
        raw = fx.raw
        assert raw.headline.strip()
        assert raw.body
        assert raw.entities and raw.categories
        assert 0.0 <= raw.provider_scores["importance"] <= 1.0
        assert (raw.latitude is None) == (raw.longitude is None)
        for s in raw.sources:
            assert s.reliability is None or 0.0 <= s.reliability <= 1.0


def test_coordinates_only_for_well_known_locations() -> None:
    with_coords = {k for k, fx in WORLD_FIXTURES.items() if fx.raw.latitude is not None}
    assert with_coords == {"hormuz", "taiwan_quake"}


def test_ids_unique_and_deterministic() -> None:
    ids = [fx.raw.provider_event_id for fx in WORLD_FIXTURES.values()]
    assert all(ids)
    assert len(set(ids)) == len(ids)
    ident = [s.source_identifier for fx in WORLD_FIXTURES.values() for s in fx.raw.sources]
    assert len(set(ident)) == len(ident)
