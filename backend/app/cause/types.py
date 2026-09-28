"""Typed Cause Engine contracts.

Scores are bounded evidence-compatibility heuristics, never causal probabilities.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CauseMode(StrEnum):
    REALTIME = "REALTIME"
    RETROSPECTIVE = "RETROSPECTIVE"


class CauseStatus(StrEnum):
    IDENTIFIED = "IDENTIFIED"
    AMBIGUOUS = "AMBIGUOUS"
    UNKNOWN = "UNKNOWN"


class ResponseState(StrEnum):
    NOT_OBSERVED = "NOT_OBSERVED"
    OPPOSITE = "OPPOSITE"
    UNCONFIRMED = "UNCONFIRMED"
    PARTIAL = "PARTIAL"
    CONFIRMED = "CONFIRMED"
    OVERREACTING = "OVERREACTING"


class CauseConfig(BaseModel):
    """Centralized, hashable configuration for all Day 5 heuristics."""

    model_config = ConfigDict(frozen=True)

    version: str = "echo-cause-config-v1"
    engine_version: str = "echo-cause-v1"
    lookback_hours: float = Field(default=6.0, gt=0, le=168)
    realtime_lookahead_minutes: float = Field(default=0.0, ge=0, le=60)
    retrospective_lookahead_hours: float = Field(default=24.0, ge=0, le=168)
    temporal_tau_hours: float = Field(default=1.0, gt=0, le=168)
    market_pattern_window_minutes: float = Field(default=30.0, gt=0, le=360)
    min_cause_score: float = Field(default=0.55, ge=0, le=1)
    ambiguity_margin: float = Field(default=0.08, ge=0, le=1)
    max_candidates: int = Field(default=25, ge=1, le=100)
    max_evidence: int = Field(default=12, ge=1, le=50)
    cluster_min_members: int = Field(default=3, ge=2, le=100)
    cluster_sync_minutes: float = Field(default=10.0, gt=0, le=120)
    cluster_min_residual_z: float = Field(default=1.0, ge=0, le=10)
    cluster_min_volume_z: float = Field(default=1.0, ge=0, le=10)
    cluster_max_events: int = Field(default=200, ge=1, le=1000)
    response_confirm_threshold: float = Field(default=0.5, ge=0, le=1)
    response_overreaction_multiplier: float = Field(default=1.75, gt=1, le=5)
    weights: dict[str, float] = Field(
        default_factory=lambda: {
            "temporal": 0.20,
            "entity": 0.15,
            "economic": 0.20,
            "graph": 0.20,
            "market": 0.15,
            "source": 0.10,
        }
    )

    @model_validator(mode="after")
    def _validate_weights(self) -> CauseConfig:
        expected = {"temporal", "entity", "economic", "graph", "market", "source"}
        if set(self.weights) != expected:
            raise ValueError(f"weights must contain exactly {sorted(expected)}")
        if any(value < 0 for value in self.weights.values()):
            raise ValueError("weights must be non-negative")
        if sum(self.weights.values()) <= 0:
            raise ValueError("weights must have a positive sum")
        return self

    def hash(self) -> str:
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def lookback_start(self, shock_at: datetime) -> datetime:
        from datetime import timedelta

        return shock_at.astimezone(UTC) - timedelta(hours=self.lookback_hours)

    def lookahead_end(self, shock_at: datetime, mode: CauseMode) -> datetime:
        from datetime import timedelta

        hours = (
            self.retrospective_lookahead_hours
            if mode == CauseMode.RETROSPECTIVE
            else self.realtime_lookahead_minutes / 60
        )
        return shock_at.astimezone(UTC) + timedelta(hours=hours)


class ObservedShock(BaseModel):
    """Normalized market-shock observation consumed by scoring and clustering."""

    model_config = ConfigDict(frozen=True)

    event_id: str
    symbol: str
    timestamp: datetime
    direction: str
    residual_z: float | None = None
    volume_z: float | None = None
    shock_score: float | None = None
    sector: str | None = None


class CauseCandidateScore(BaseModel):
    """Fully explainable score for one candidate event."""

    model_config = ConfigDict(frozen=True)

    event_id: str
    title: str
    score: float = Field(ge=0, le=1)
    temporal_score: float = Field(ge=0, le=1)
    entity_score: float = Field(ge=0, le=1)
    economic_score: float = Field(ge=0, le=1)
    graph_score: float = Field(ge=0, le=1)
    market_score: float = Field(ge=0, le=1)
    source_score: float = Field(ge=0, le=1)
    directional_consistency: float = Field(ge=-1, le=1)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    graph_paths: list[dict[str, Any]] = Field(default_factory=list)


class CauseInvestigationResult(BaseModel):
    """Public/domain result; persisted investigations reconstruct this contract."""

    model_config = ConfigDict(frozen=True)

    investigation_id: str
    shock_event_id: str
    graph_snapshot_id: str
    created_at: datetime
    data_cutoff_at: datetime
    mode: CauseMode
    status: CauseStatus
    engine_version: str
    config_version: str
    config_hash: str
    candidates: list[CauseCandidateScore]
    metadata: dict[str, Any] = Field(default_factory=dict)


class ClusterShockValue(BaseModel):
    """Structured cluster observation, deliberately not a probability."""

    model_config = ConfigDict(frozen=True)

    cluster_id: str
    cluster_key: str
    as_of: datetime
    direction: str
    members: list[str]
    member_count: int = Field(ge=0)
    abnormal_count: int = Field(ge=0)
    strength: float = Field(ge=0, le=1)
    synchronization: float = Field(ge=0, le=1)
    volume_confirmation: float = Field(ge=0, le=1)
    graph_connectivity: float = Field(ge=0, le=1)
    source_event_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
