"""Pure, bounded, deterministic ShockGraph propagation."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from app.graph.types import (
    CompanyExposure,
    ExposurePath,
    GraphEdgeValue,
    GraphNodeType,
    GraphNodeValue,
)


@dataclass(frozen=True)
class PropagationConfig:
    max_depth: int = 3
    path_decay_lambda: float = 0.45
    min_edge_weight: float = 0.05
    min_edge_confidence: float = 0.05
    min_result_exposure: float = 0.02
    max_results: int = 25
    max_paths_per_company: int = 3

    def __post_init__(self) -> None:
        if not 1 <= self.max_depth <= 3:
            raise ValueError("max_depth must be between 1 and 3")
        if self.path_decay_lambda < 0:
            raise ValueError("path_decay_lambda must be non-negative")
        if not 0 <= self.min_edge_weight <= 1 or not 0 <= self.min_edge_confidence <= 1:
            raise ValueError("edge thresholds must be in [0,1]")


@dataclass(frozen=True)
class _CandidatePath:
    company_id: str
    nodes: tuple[str, ...]
    edges: tuple[GraphEdgeValue, ...]
    contribution: float
    confidence: float


def _clamp(value: float) -> float:
    return max(-1.0, min(1.0, value))


def _path(
    source: str,
    edge: GraphEdgeValue,
    nodes: tuple[str, ...],
    edges: tuple[GraphEdgeValue, ...],
    strength: float,
    event_confidence: float,
    cfg: PropagationConfig,
) -> _CandidatePath:
    next_edges = (*edges, edge)
    depth = len(next_edges)
    direction = math.prod(item.sign for item in next_edges)
    weight = math.prod(item.weight for item in next_edges)
    confidence = event_confidence * math.prod(item.confidence for item in next_edges)
    decay = math.exp(-cfg.path_decay_lambda * (depth - 1))
    return _CandidatePath(
        company_id=edge.target_node_id,
        nodes=(*nodes, edge.target_node_id),
        edges=next_edges,
        contribution=strength * direction * weight * decay,
        confidence=max(0.0, min(1.0, confidence)),
    )


def propagate(
    *,
    channel_strengths: dict[str, float],
    event_confidence: float,
    nodes: Iterable[GraphNodeValue],
    edges: Iterable[GraphEdgeValue],
    direct_company_ids: Iterable[str] = (),
    config: PropagationConfig | None = None,
) -> list[CompanyExposure]:
    """Return stable ranked company exposures; values are bounded exposure, not returns."""
    cfg = config or PropagationConfig()
    node_map = {node.id: node for node in nodes}
    adjacency: dict[str, list[GraphEdgeValue]] = defaultdict(list)
    for edge in edges:
        if edge.weight >= cfg.min_edge_weight and edge.confidence >= cfg.min_edge_confidence:
            adjacency[edge.source_node_id].append(edge)
    for values in adjacency.values():
        values.sort(key=lambda edge: (edge.target_node_id, edge.id))
    candidates: dict[str, list[_CandidatePath]] = defaultdict(list)

    def walk(
        current: str,
        strength: float,
        nodes_seen: tuple[str, ...],
        edges_seen: tuple[GraphEdgeValue, ...],
        depth: int,
    ) -> None:
        if depth >= cfg.max_depth:
            return
        for edge in adjacency.get(current, []):
            if edge.target_node_id in nodes_seen:
                continue
            candidate = _path(
                current, edge, nodes_seen, edges_seen, strength, event_confidence, cfg
            )
            target = node_map.get(edge.target_node_id)
            if target and target.node_type == GraphNodeType.COMPANY:
                candidates[target.id].append(candidate)
            walk(edge.target_node_id, strength, candidate.nodes, candidate.edges, depth + 1)

    for channel, strength in sorted(channel_strengths.items()):
        if not math.isfinite(strength) or abs(strength) < 1e-12:
            continue
        walk(
            channel if channel.startswith("channel:") else f"channel:{channel}",
            float(strength),
            (channel if channel.startswith("channel:") else f"channel:{channel}",),
            (),
            0,
        )

    for company_id in sorted(set(direct_company_ids)):
        if node_map.get(company_id) and node_map[company_id].node_type == GraphNodeType.COMPANY:
            candidates[company_id].append(
                _CandidatePath(
                    company_id, ("event", company_id), (), 1.0, max(0.0, min(1.0, event_confidence))
                )
            )

    results: list[CompanyExposure] = []
    for company_id, paths in sorted(candidates.items()):
        paths.sort(
            key=lambda path: (
                -abs(path.contribution),
                path.nodes,
                tuple(edge.id for edge in path.edges),
            )
        )
        bounded = _clamp(math.tanh(sum(path.contribution for path in paths)))
        if abs(bounded) < cfg.min_result_exposure:
            continue
        confidence = _clamp(1.0 - math.prod(1.0 - min(path.confidence, 0.999) for path in paths))
        node = node_map[company_id]
        results.append(
            CompanyExposure(
                symbol=node.symbol or node.canonical_name,
                node_id=node.id,
                company_name=node.canonical_name,
                exposure=round(bounded, 6),
                confidence=round(confidence, 6),
                rank=0,
                paths=[
                    ExposurePath(
                        nodes=list(path.nodes),
                        edge_ids=[edge.id for edge in path.edges],
                        relationships=[edge.relationship_type for edge in path.edges],
                        contribution=round(_clamp(path.contribution), 6),
                        confidence=round(path.confidence, 6),
                        depth=len(path.edges),
                    )
                    for path in paths[: cfg.max_paths_per_company]
                ],
                direction="POSITIVE" if bounded > 0 else "NEGATIVE",
                top_reason=(
                    paths[0].edges[-1].relationship_type.value
                    if paths and paths[0].edges
                    else "DIRECT_EVENT_EXPOSURE"
                ),
            )
        )
    results.sort(key=lambda item: (-abs(item.exposure), -item.confidence, item.symbol))
    return [
        item.model_copy(update={"rank": index})
        for index, item in enumerate(results[: cfg.max_results], 1)
    ]
