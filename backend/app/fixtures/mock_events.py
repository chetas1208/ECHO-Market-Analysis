"""Clearly-labelled MOCK events used for the Day 1 end-to-end demo and tests.

These are fixtures, not real World Monitor data. Every fixture has ``is_mock=True`` and a
``metadata.fixture == "mock"`` marker.
"""

from datetime import UTC, datetime

from app.schemas.event import EventCreate, SourceType

MOCK_HORMUZ_EVENT_ID = "evt_mock_hormuz_naval_001"

MOCK_HORMUZ_EVENT = EventCreate(
    id=MOCK_HORMUZ_EVENT_ID,
    timestamp=datetime(2026, 9, 20, 17, 0, 0, tzinfo=UTC),
    source_type=SourceType.WORLD,
    event_type="geopolitical_shipping_disruption",
    title="Strait of Hormuz — Increased Naval Activity",
    summary=(
        "MOCK FIXTURE: Elevated naval deployments reported near the Strait of Hormuz, "
        "raising the risk of disruption to crude oil and LNG tanker traffic."
    ),
    entities=["Strait of Hormuz"],
    companies=[],
    locations=["Middle East"],
    economic_channels={
        "oil_supply": -0.82,
        "shipping_costs": 0.77,
        "energy_prices": 0.73,
        "global_trade": -0.61,
    },
    severity=0.88,
    novelty=0.74,
    corroboration=0.91,
    confidence=0.91,
    source_refs=[{"name": "World Monitor (mock fixture)", "url": None}],
    metadata={
        "fixture": "mock",
        "note": "Synthetic Day 1 fixture; not derived from a live feed.",
    },
    is_mock=True,
)

MOCK_EVENTS: list[EventCreate] = [MOCK_HORMUZ_EVENT]
