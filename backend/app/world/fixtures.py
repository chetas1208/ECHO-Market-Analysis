"""Deterministic synthetic world-event fixtures for REPLAY mode and tests.

Everything here is fictional test data: publisher names are clearly synthetic ("Replay Wire A"),
no source URL is set, and every event carries ``is_replay=True`` so it can never be presented as
live reporting. Module-level constants only; no clock, no randomness, no I/O.

``expected_country`` is an ISO 3166-1 alpha-2 code (what ``geo.normalize_geo`` should resolve),
or ``None`` when the event has no single country (e.g. a chokepoint described by region only).
``expected_channels`` maps channel name -> expected SIGN (-1 or +1) of directional pressure.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, ConfigDict

from app.world.types import EventClass, RawWorldEvent, SourceRef

_PROVIDER = "replay"


class WorldFixture(BaseModel):
    """A replayable raw event plus the classification/channel outcome a correct pipeline yields."""

    model_config = ConfigDict(frozen=True)

    key: str
    raw: RawWorldEvent
    expected_class: EventClass
    expected_channels: dict[str, int]  # channel -> expected sign (-1 / +1)
    expected_country: str | None = None  # ISO2, None if no single country


def _ref(
    *,
    name: str,
    group: str,
    identifier: str,
    headline: str,
    occurred_at: datetime,
    published_offset_min: int,
    retrieved_offset_min: int,
    reliability: float,
) -> SourceRef:
    return SourceRef(
        provider=_PROVIDER,
        source_name=name,
        source_url=None,
        source_identifier=identifier,
        headline=headline,
        published_at=occurred_at + timedelta(minutes=published_offset_min),
        retrieved_at=occurred_at + timedelta(minutes=retrieved_offset_min),
        source_group=group,
        reliability=reliability,
        metadata={"synthetic": True},
    )


# --- hormuz -------------------------------------------------------------------------------------
_HORMUZ_AT = datetime(2026, 9, 16, 9, 0, tzinfo=UTC)
_HORMUZ_HEADLINE = "Strait of Hormuz — Increased Naval Activity"
_HORMUZ = WorldFixture(
    key="hormuz",
    raw=RawWorldEvent(
        provider=_PROVIDER,
        provider_event_id="replay-hormuz-001",
        headline=_HORMUZ_HEADLINE,
        body=(
            "Increased naval activity reported near the Strait of Hormuz. Several tankers are "
            "slowing or holding position and insurers are reviewing war-risk cover for "
            "transits through the shipping lane. (Synthetic replay data.)"
        ),
        occurred_at=_HORMUZ_AT,
        sources=[
            _ref(
                name="Replay Wire A",
                group="replay_wire_a",
                identifier="rwa-hormuz-001",
                headline=_HORMUZ_HEADLINE,
                occurred_at=_HORMUZ_AT,
                published_offset_min=2,
                retrieved_offset_min=4,
                reliability=0.8,
            ),
            _ref(
                name="Replay Wire B",
                group="replay_wire_b",
                identifier="rwb-hormuz-001",
                headline="Naval build-up near Hormuz slows tanker traffic",
                occurred_at=_HORMUZ_AT,
                published_offset_min=5,
                retrieved_offset_min=7,
                reliability=0.75,
            ),
        ],
        region="Middle East",
        latitude=26.57,
        longitude=56.25,
        entities=["Strait of Hormuz", "Persian Gulf", "crude oil"],
        categories=["shipping", "maritime security", "energy"],
        provider_scores={"importance": 0.85},
        is_replay=True,
    ),
    expected_class=EventClass.SHIPPING_DISRUPTION,
    expected_channels={
        "oil_supply": -1,
        "energy_prices": 1,
        "shipping_costs": 1,
        "global_trade": -1,
    },
    expected_country=None,
)

# --- taiwan_quake -------------------------------------------------------------------------------
_QUAKE_AT = datetime(2026, 9, 14, 2, 30, tzinfo=UTC)
_QUAKE_HEADLINE = "Magnitude 7.4 earthquake strikes off Hualien, Taiwan"
_TAIWAN_QUAKE = WorldFixture(
    key="taiwan_quake",
    raw=RawWorldEvent(
        provider=_PROVIDER,
        provider_event_id="replay-taiwan-quake-001",
        headline=_QUAKE_HEADLINE,
        body=(
            "A strong earthquake struck near Hualien, Taiwan. Semiconductor fabs in the island's "
            "science parks are inspecting equipment; wafer production may be interrupted while "
            "safety checks continue. (Synthetic replay data.)"
        ),
        occurred_at=_QUAKE_AT,
        sources=[
            _ref(
                name="Replay Wire A",
                group="replay_wire_a",
                identifier="rwa-quake-001",
                headline=_QUAKE_HEADLINE,
                occurred_at=_QUAKE_AT,
                published_offset_min=3,
                retrieved_offset_min=5,
                reliability=0.8,
            ),
            _ref(
                name="Replay Geoscience Desk",
                group="replay_geoscience_desk",
                identifier="rgd-quake-001",
                headline="Strong quake near Hualien; fab production risk under review",
                occurred_at=_QUAKE_AT,
                published_offset_min=6,
                retrieved_offset_min=8,
                reliability=0.85,
            ),
        ],
        country="Taiwan",
        region="East Asia",
        city="Hualien",
        latitude=23.99,
        longitude=121.60,
        entities=["Taiwan", "Hualien", "semiconductor", "TSMC"],
        categories=["natural disaster", "earthquake", "technology supply chain"],
        magnitude={"richter": 7.4},
        provider_scores={"importance": 0.9},
        is_replay=True,
    ),
    expected_class=EventClass.NATURAL_DISASTER,
    expected_channels={"semiconductor_supply": -1},
    expected_country="TW",
)

# --- cloud_outage -------------------------------------------------------------------------------
_CLOUD_AT = datetime(2026, 9, 15, 14, 20, tzinfo=UTC)
_CLOUD_HEADLINE = "Major cloud region outage disrupts services across North America"
_CLOUD_OUTAGE = WorldFixture(
    key="cloud_outage",
    raw=RawWorldEvent(
        provider=_PROVIDER,
        provider_event_id="replay-cloud-outage-001",
        headline=_CLOUD_HEADLINE,
        body=(
            "A fictional hyperscaler, Stratus Cloud, reports a multi-hour outage in its US East "
            "region. Compute, storage and networking services are unavailable for many "
            "customers. (Synthetic replay data.)"
        ),
        occurred_at=_CLOUD_AT,
        sources=[
            _ref(
                name="Replay Tech Bulletin",
                group="replay_tech_bulletin",
                identifier="rtb-cloud-001",
                headline=_CLOUD_HEADLINE,
                occurred_at=_CLOUD_AT,
                published_offset_min=4,
                retrieved_offset_min=6,
                reliability=0.7,
            ),
        ],
        country="United States",
        region="North America",
        entities=["Stratus Cloud", "United States"],
        categories=["infrastructure outage", "cloud", "technology"],
        provider_scores={"importance": 0.7},
        is_replay=True,
    ),
    expected_class=EventClass.INFRASTRUCTURE_OUTAGE,
    expected_channels={"infrastructure_availability": -1},
    expected_country="US",
)

# --- oil_infra ----------------------------------------------------------------------------------
_OIL_AT = datetime(2026, 9, 15, 5, 45, tzinfo=UTC)
_OIL_HEADLINE = "Drone attack halts crude pipeline pumping station and refinery in Saudi Arabia"
_OIL_INFRA = WorldFixture(
    key="oil_infra",
    raw=RawWorldEvent(
        provider=_PROVIDER,
        provider_event_id="replay-oil-infra-001",
        headline=_OIL_HEADLINE,
        body=(
            "An attack on an oil pipeline pumping station and adjacent refinery has forced a "
            "halt in crude flows and refined product output. Operators are assessing damage and "
            "restart timelines. (Synthetic replay data.)"
        ),
        occurred_at=_OIL_AT,
        sources=[
            _ref(
                name="Replay Wire B",
                group="replay_wire_b",
                identifier="rwb-oil-001",
                headline=_OIL_HEADLINE,
                occurred_at=_OIL_AT,
                published_offset_min=3,
                retrieved_offset_min=5,
                reliability=0.75,
            ),
            _ref(
                name="Replay Energy Desk",
                group="replay_energy_desk",
                identifier="red-oil-001",
                headline="Pipeline and refinery outage cuts Saudi crude flows",
                occurred_at=_OIL_AT,
                published_offset_min=8,
                retrieved_offset_min=10,
                reliability=0.7,
            ),
        ],
        country="Saudi Arabia",
        region="Middle East",
        entities=["Saudi Arabia", "crude oil", "pipeline", "refinery"],
        categories=["energy", "infrastructure", "attack"],
        provider_scores={"importance": 0.88},
        is_replay=True,
    ),
    expected_class=EventClass.ENERGY_SUPPLY_DISRUPTION,
    expected_channels={"oil_supply": -1, "energy_prices": 1},
    expected_country="SA",
)

# --- cyber_incident -----------------------------------------------------------------------------
_CYBER_AT = datetime(2026, 9, 17, 11, 10, tzinfo=UTC)
_CYBER_HEADLINE = "Ransomware attack knocks out logistics software vendor Meridian Freight Systems"
_CYBER_INCIDENT = WorldFixture(
    key="cyber_incident",
    raw=RawWorldEvent(
        provider=_PROVIDER,
        provider_event_id="replay-cyber-incident-001",
        headline=_CYBER_HEADLINE,
        body=(
            "Fictional vendor Meridian Freight Systems disclosed a ransomware incident that took "
            "its shipment-tracking platform offline. Carriers and shippers relying on the "
            "software report manual workarounds. (Synthetic replay data.)"
        ),
        occurred_at=_CYBER_AT,
        sources=[
            _ref(
                name="Replay Tech Bulletin",
                group="replay_tech_bulletin",
                identifier="rtb-cyber-001",
                headline=_CYBER_HEADLINE,
                occurred_at=_CYBER_AT,
                published_offset_min=5,
                retrieved_offset_min=7,
                reliability=0.7,
            ),
            _ref(
                name="Replay Security Desk",
                group="replay_security_desk",
                identifier="rsd-cyber-001",
                headline="Ransomware hits freight software provider; operations disrupted",
                occurred_at=_CYBER_AT,
                published_offset_min=9,
                retrieved_offset_min=12,
                reliability=0.75,
            ),
        ],
        country="United States",
        region="North America",
        entities=["Meridian Freight Systems", "United States"],
        categories=["cyber", "ransomware", "logistics"],
        provider_scores={"importance": 0.65},
        is_replay=True,
    ),
    expected_class=EventClass.CYBER_INCIDENT,
    expected_channels={"cybersecurity_risk": 1},
    expected_country="US",
)

# --- sanction -----------------------------------------------------------------------------------
_SANCTION_AT = datetime(2026, 9, 17, 16, 0, tzinfo=UTC)
_SANCTION_HEADLINE = "European Union imposes new export sanctions on Belarus potash sector"
_SANCTION = WorldFixture(
    key="sanction",
    raw=RawWorldEvent(
        provider=_PROVIDER,
        provider_event_id="replay-sanction-001",
        headline=_SANCTION_HEADLINE,
        body=(
            "The European Union announced a new round of sanctions restricting exports and "
            "financing tied to Belarus's potash sector, citing geopolitical tensions. "
            "Compliance teams are reviewing exposure. (Synthetic replay data.)"
        ),
        occurred_at=_SANCTION_AT,
        sources=[
            _ref(
                name="Replay Wire A",
                group="replay_wire_a",
                identifier="rwa-sanction-001",
                headline=_SANCTION_HEADLINE,
                occurred_at=_SANCTION_AT,
                published_offset_min=4,
                retrieved_offset_min=6,
                reliability=0.8,
            ),
        ],
        country="Belarus",
        region="Eastern Europe",
        entities=["European Union", "Belarus", "potash"],
        categories=["sanctions", "trade policy", "geopolitics"],
        provider_scores={"importance": 0.6},
        is_replay=True,
    ),
    expected_class=EventClass.SANCTION,
    expected_channels={"regulatory_risk": 1, "geopolitical_risk": 1},
    expected_country="BY",
)

WORLD_FIXTURES: dict[str, WorldFixture] = {
    f.key: f
    for f in (_HORMUZ, _TAIWAN_QUAKE, _CLOUD_OUTAGE, _OIL_INFRA, _CYBER_INCIDENT, _SANCTION)
}
