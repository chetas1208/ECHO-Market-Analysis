"""ECHO-owned world-event types. Provider payloads (World Monitor etc.) stop at the adapter.

All timestamps are timezone-aware UTC. Scores are HEURISTIC in [0,1]; none is a calibrated
probability. Economic channel values are directional pressure scores in [-1, 1]
(-1 strong negative pressure, 0 none identified, +1 strong positive), NOT expected % moves.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EventClass(StrEnum):
    GEOPOLITICAL_ESCALATION = "geopolitical_escalation"
    MILITARY_CONFLICT = "military_conflict"
    SANCTION = "sanction"
    REGULATORY_EVENT = "regulatory_event"
    SHIPPING_DISRUPTION = "shipping_disruption"
    PORT_DISRUPTION = "port_disruption"
    ENERGY_SUPPLY_DISRUPTION = "energy_supply_disruption"
    COMMODITY_SHOCK = "commodity_shock"
    NATURAL_DISASTER = "natural_disaster"
    CYBER_INCIDENT = "cyber_incident"
    INFRASTRUCTURE_OUTAGE = "infrastructure_outage"
    TECHNOLOGY_SUPPLY_SHOCK = "technology_supply_shock"
    MACRO_EVENT = "macro_event"
    OTHER = "other"


class WorldProviderName(StrEnum):
    WORLD_MONITOR = "world_monitor"
    REPLAY = "replay"


class WorldProviderState(StrEnum):
    UNCONFIGURED = "UNCONFIGURED"
    CONNECTING = "CONNECTING"
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    STALE = "STALE"
    ERROR = "ERROR"
    REPLAY = "REPLAY"


class WorldMode(StrEnum):
    """What the UI must show for the world feed. Replay must NEVER masquerade as LIVE."""

    LIVE = "LIVE"
    REPLAY = "REPLAY"
    OFFLINE = "OFFLINE"


class SourceRef(BaseModel):
    """One piece of evidence for an event. Never dropped during normalization."""

    model_config = ConfigDict(frozen=True)

    provider: str  # world_monitor | replay
    source_name: str  # publisher, e.g. "Reuters"
    source_url: str | None = None
    source_identifier: str | None = None  # provider-side id
    headline: str | None = None
    published_at: datetime | None = None
    retrieved_at: datetime
    source_group: str | None = None  # publisher family for independence (e.g. "reuters")
    syndicated_from: str | None = None  # original publisher if a republication
    reliability: float | None = Field(default=None, ge=0, le=1)  # provider-supplied, if any
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("published_at", "retrieved_at")
    @classmethod
    def _aware(cls, v: datetime | None) -> datetime | None:
        if v is None:
            return v
        if v.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware")
        return v.astimezone(UTC)


class RawWorldEvent(BaseModel):
    """Provider-agnostic input produced by an adapter. The ONLY thing that crosses the boundary."""

    provider: str
    provider_event_id: str | None = None
    headline: str
    body: str | None = None
    occurred_at: datetime  # best estimate of when it happened (published_at fallback)
    sources: list[SourceRef] = Field(default_factory=list)
    country: str | None = None  # raw, un-normalized
    region: str | None = None
    city: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    entities: list[str] = Field(default_factory=list)  # raw names
    categories: list[str] = Field(default_factory=list)  # provider tags/categories
    magnitude: dict[str, float] = Field(default_factory=dict)  # e.g. {"richter": 7.4}
    provider_scores: dict[str, float] = Field(default_factory=dict)  # provider importance etc.
    is_replay: bool = False

    @field_validator("occurred_at")
    @classmethod
    def _aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware")
        return v.astimezone(UTC)

    @field_validator("headline")
    @classmethod
    def _nonempty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("headline must be non-empty")
        return v


class GeoInfo(BaseModel):
    country: str | None = None  # ISO 3166-1 alpha-2
    country_name: str | None = None
    region: str | None = None
    city: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    chokepoint: str | None = None  # e.g. "Strait of Hormuz"
    resolved: bool = False  # False = unavailable (never invented)


class NormalizedEntity(BaseModel):
    canonical: str
    kind: str  # country|region|city|company|commodity|infrastructure|organization|other
    raw: str


class EventScores(BaseModel):
    """All HEURISTIC, bounded [0,1], deterministic. Not calibrated probabilities."""

    severity: float = Field(ge=0, le=1)  # economic significance IF true (not sentiment)
    novelty: float = Field(ge=0, le=1)  # difference vs recently observed information
    corroboration: float = Field(ge=0, le=1)  # independent-source support score
    confidence: float = Field(ge=0, le=1)  # interpretation confidence (extraction/quality)
    components: dict[str, Any] = Field(default_factory=dict)  # transparent breakdown


class NormalizedWorldEvent(BaseModel):
    """Everything needed to persist/merge one canonical world event (pre-persistence)."""

    event_class: EventClass
    title: str
    summary: str | None = None
    occurred_at: datetime
    geo: GeoInfo
    entities: list[NormalizedEntity] = Field(default_factory=list)
    economic_channels: dict[str, float] = Field(default_factory=dict)  # each in [-1, 1]
    channel_evidence: dict[str, list[str]] = Field(default_factory=dict)  # why each channel
    sources: list[SourceRef]
    fingerprint: str
    scores: EventScores | None = None  # filled by the scoring stage
    text_sentiment: dict[str, Any] | None = None  # optional FinancialTextAnalyzer output
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorldProviderHealth(BaseModel):
    provider: WorldProviderName
    configured: bool
    state: WorldProviderState
    mode: WorldMode
    last_success_at: datetime | None = None
    last_event_at: datetime | None = None
    events_received: int = 0
    malformed_events: int = 0
    last_error: str | None = None
    poll_interval_s: float | None = None
    retry_after_until: datetime | None = None
