"""Load and validate the checked-in ShockGraph seed artifact."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.graph.types import GraphEdgeValue, GraphNodeType, GraphNodeValue, RelationshipType

SEED_PATH = Path(__file__).resolve().parents[2] / "data" / "graph" / "seed.json"


class SeedNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    node_type: GraphNodeType
    canonical_name: str = Field(min_length=1)
    symbol: str | None = None
    external_ids: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SeedEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    target: str
    relationship: RelationshipType
    sign: int
    weight: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    provenance: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_sign(self) -> SeedEdge:
        if self.sign not in (-1, 1):
            raise ValueError("edge sign must be -1 or +1")
        return self


@dataclass(frozen=True)
class SeedGraph:
    graph_version: str
    provenance: dict[str, Any]
    nodes: tuple[GraphNodeValue, ...]
    edges: tuple[GraphEdgeValue, ...]


def _edge_id(edge: SeedEdge) -> str:
    import hashlib

    raw = "|".join(
        (
            edge.source,
            edge.target,
            edge.relationship.value,
            str(edge.sign),
        )
    )
    return f"edge_{hashlib.sha256(raw.encode()).hexdigest()[:24]}"


def load_seed(path: Path = SEED_PATH, *, now: datetime | None = None) -> SeedGraph:
    payload = json.loads(path.read_text(encoding="utf-8"))
    default_provenance = payload.get("provenance")
    if not isinstance(default_provenance, dict) or not default_provenance:
        raise ValueError("seed graph requires top-level provenance")
    nodes = tuple(SeedNode.model_validate(item) for item in payload.get("nodes", []))
    node_ids = {node.id for node in nodes}
    if len(node_ids) != len(nodes):
        raise ValueError("seed graph contains duplicate node ids")
    at = (now or datetime(2026, 1, 1, tzinfo=UTC)).astimezone(UTC)
    edges: list[GraphEdgeValue] = []
    seen_pairs: set[tuple[str, str, str]] = set()
    for raw in payload.get("edges", []):
        edge = SeedEdge.model_validate(raw)
        if edge.source not in node_ids or edge.target not in node_ids:
            raise ValueError(f"edge references missing node: {edge.source} -> {edge.target}")
        key = (edge.source, edge.target, edge.relationship.value)
        if key in seen_pairs:
            raise ValueError(f"duplicate graph edge: {key}")
        seen_pairs.add(key)
        edges.append(
            GraphEdgeValue(
                id=_edge_id(edge),
                source_node_id=edge.source,
                target_node_id=edge.target,
                relationship_type=edge.relationship,
                sign=edge.sign,
                weight=edge.weight,
                confidence=edge.confidence,
                provenance=edge.provenance or default_provenance,
                valid_from=at,
            )
        )
    if not edges:
        raise ValueError("seed graph must contain edges")
    if not any(node.node_type == GraphNodeType.COMPANY for node in nodes):
        raise ValueError("seed graph must contain companies")
    return SeedGraph(
        graph_version=str(payload.get("graph_version", "echo-graph-v1")),
        provenance=default_provenance,
        nodes=tuple(
            sorted(
                (GraphNodeValue.model_validate(node.model_dump()) for node in nodes),
                key=lambda n: n.id,
            )
        ),
        edges=tuple(sorted(edges, key=lambda e: e.id)),
    )
