"""Public Cause Engine and bidirectional market-impact responses."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.cause.types import CauseMode, CauseStatus, ResponseState


class CauseCandidateOut(BaseModel):
    event_id: str
    title: str
    score: float
    temporal_score: float
    entity_score: float
    economic_score: float
    graph_score: float
    market_score: float
    source_score: float
    directional_consistency: float
    evidence: list[dict[str, Any]]
    graph_paths: list[dict[str, Any]]


class CauseInvestigationOut(BaseModel):
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
    candidates: list[CauseCandidateOut]
    metadata: dict[str, Any] = Field(default_factory=dict)


class MarketImpactCompanyOut(BaseModel):
    symbol: str
    exposure: float
    confidence: float
    actual_residual_z: float | None
    response_state: ResponseState
    paths: list[dict[str, Any]]


class MarketImpactOut(BaseModel):
    event_id: str
    graph_snapshot_id: str
    graph_version: str
    data_cutoff_at: datetime
    market_confirmation_unavailable: bool
    companies: list[MarketImpactCompanyOut]
    unmapped_channels: list[str]


class ClusterShockOut(BaseModel):
    cluster_id: str
    cluster_key: str
    as_of: datetime
    direction: str
    members: list[str]
    member_count: int
    abnormal_count: int
    strength: float
    synchronization: float
    volume_confirmation: float
    graph_connectivity: float
    source_event_id: str | None
    metadata: dict[str, Any]


class ClusterShockListOut(BaseModel):
    items: list[ClusterShockOut]
    total: int
