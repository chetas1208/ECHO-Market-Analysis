"""Typed graph and exposure contracts. Scores are bounded heuristics, not returns."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class GraphNodeType(StrEnum):
    COMPANY = "company"
    COMMODITY = "commodity"
    GEOGRAPHY = "geography"
    TECHNOLOGY = "technology"
    SECTOR = "sector"
    INFRASTRUCTURE = "infrastructure"
    CHANNEL = "channel"


class RelationshipType(StrEnum):
    SUPPLIER_OF = "SUPPLIER_OF"
    CUSTOMER_OF = "CUSTOMER_OF"
    COMPETITOR_OF = "COMPETITOR_OF"
    SUBSTITUTE_FOR = "SUBSTITUTE_FOR"
    COMPLEMENT_TO = "COMPLEMENT_TO"
    EXPOSED_TO_COMMODITY = "EXPOSED_TO_COMMODITY"
    OPERATES_IN_GEOGRAPHY = "OPERATES_IN_GEOGRAPHY"
    GEOGRAPHIC_EXPOSURE = "GEOGRAPHIC_EXPOSURE"
    REGULATORY_EXPOSURE = "REGULATORY_EXPOSURE"
    TECHNOLOGY_DEPENDENCY = "TECHNOLOGY_DEPENDENCY"
    RISK_SIMILARITY = "RISK_SIMILARITY"
    MEMBER_OF_SECTOR = "MEMBER_OF_SECTOR"
    DEPENDS_ON_INFRASTRUCTURE = "DEPENDS_ON_INFRASTRUCTURE"
    DEPENDS_ON_ROUTE = "DEPENDS_ON_ROUTE"
    PRODUCES_COMMODITY = "PRODUCES_COMMODITY"
    CONSUMES_COMMODITY = "CONSUMES_COMMODITY"
    CHANNEL_EXPOSURE = "CHANNEL_EXPOSURE"


class GraphNodeValue(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    node_type: GraphNodeType
    canonical_name: str
    symbol: str | None = None
    external_ids: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class GraphEdgeValue(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    source_node_id: str
    target_node_id: str
    relationship_type: RelationshipType
    sign: int = Field(ge=-1, le=1)
    weight: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    provenance: dict[str, Any] = Field(min_length=1)
    valid_from: datetime
    valid_to: datetime | None = None

    @field_validator("sign")
    @classmethod
    def _signed(cls, value: int) -> int:
        if value not in (-1, 1):
            raise ValueError("edge sign must be -1 or +1")
        return value


class GraphSnapshotValue(BaseModel):
    model_config = ConfigDict(frozen=True)

    snapshot_id: str
    graph_version: str
    created_at: datetime
    node_count: int = Field(ge=0)
    edge_count: int = Field(ge=0)
    content_hash: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExposurePath(BaseModel):
    nodes: list[str]
    edge_ids: list[str]
    relationships: list[RelationshipType]
    contribution: float
    confidence: float
    depth: int


class CompanyExposure(BaseModel):
    symbol: str
    node_id: str
    company_name: str
    exposure: float
    confidence: float
    rank: int
    paths: list[ExposurePath]
    direction: str
    top_reason: str | None = None


class GraphProjection(BaseModel):
    event_id: str
    graph_snapshot_id: str
    graph_version: str
    nodes: list[GraphNodeValue]
    edges: list[GraphEdgeValue]
    companies: list[CompanyExposure]
    unmapped_channels: list[str] = Field(default_factory=list)
    diagnostics: dict[str, Any] = Field(default_factory=dict)
