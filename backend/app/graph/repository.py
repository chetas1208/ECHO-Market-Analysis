"""PostgreSQL persistence for graph truth and immutable snapshot copies."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.graph.seed import SeedGraph
from app.graph.types import GraphEdgeValue, GraphNodeValue, GraphSnapshotValue
from app.models import GraphEdge, GraphNode, GraphSnapshot, GraphSnapshotEdge, GraphSnapshotNode


def _canonical_payload(
    nodes: Sequence[GraphNodeValue], edges: Sequence[GraphEdgeValue]
) -> dict[str, Any]:
    return {
        "nodes": [node.model_dump(mode="json") for node in sorted(nodes, key=lambda item: item.id)],
        "edges": [edge.model_dump(mode="json") for edge in sorted(edges, key=lambda item: item.id)],
    }


def graph_content_hash(nodes: Sequence[GraphNodeValue], edges: Sequence[GraphEdgeValue]) -> str:
    encoded = json.dumps(
        _canonical_payload(nodes, edges), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _node_value(row: GraphNode | GraphSnapshotNode) -> GraphNodeValue:
    return GraphNodeValue(
        id=row.id if isinstance(row, GraphNode) else row.node_id,
        node_type=row.node_type,
        canonical_name=row.canonical_name,
        symbol=row.symbol,
        external_ids=dict(row.external_ids or {}),
        metadata=dict(row.metadata_ or {}),
    )


def _edge_value(row: GraphEdge | GraphSnapshotEdge) -> GraphEdgeValue:
    return GraphEdgeValue(
        id=row.id if isinstance(row, GraphEdge) else row.edge_id,
        source_node_id=row.source_node_id,
        target_node_id=row.target_node_id,
        relationship_type=row.relationship_type,
        sign=row.sign,
        weight=row.weight,
        confidence=row.confidence,
        provenance=dict(row.provenance or {}),
        valid_from=row.valid_from,
        valid_to=row.valid_to,
    )


class GraphRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_snapshot(self, seed: SeedGraph) -> GraphSnapshotValue:
        await self.session.execute(
            insert(GraphNode)
            .values(
                [
                    {
                        "id": node.id,
                        "node_type": node.node_type.value,
                        "canonical_name": node.canonical_name,
                        "symbol": node.symbol,
                        "external_ids": node.external_ids,
                        "metadata_": node.metadata,
                    }
                    for node in seed.nodes
                ]
            )
            .on_conflict_do_nothing(index_elements=[GraphNode.id])
        )
        await self.session.execute(
            insert(GraphEdge)
            .values(
                [
                    {
                        "id": edge.id,
                        "source_node_id": edge.source_node_id,
                        "target_node_id": edge.target_node_id,
                        "relationship_type": edge.relationship_type.value,
                        "sign": edge.sign,
                        "weight": edge.weight,
                        "confidence": edge.confidence,
                        "provenance": edge.provenance,
                        "valid_from": edge.valid_from,
                        "valid_to": edge.valid_to,
                    }
                    for edge in seed.edges
                ]
            )
            .on_conflict_do_nothing(index_elements=[GraphEdge.id])
        )
        nodes = [
            _node_value(row)
            for row in (await self.session.execute(select(GraphNode).order_by(GraphNode.id)))
            .scalars()
            .all()
        ]
        edges = [
            _edge_value(row)
            for row in (await self.session.execute(select(GraphEdge).order_by(GraphEdge.id)))
            .scalars()
            .all()
        ]
        content_hash = graph_content_hash(nodes, edges)
        snapshot_id = f"gs_{content_hash[:20]}"
        await self.session.execute(
            insert(GraphSnapshot)
            .values(
                snapshot_id=snapshot_id,
                graph_version=seed.graph_version,
                node_count=len(nodes),
                edge_count=len(edges),
                content_hash=content_hash,
                metadata_={"seed_provenance": seed.provenance},
            )
            .on_conflict_do_nothing(index_elements=[GraphSnapshot.snapshot_id])
        )
        await self.session.execute(
            insert(GraphSnapshotNode)
            .values(
                [
                    {
                        "snapshot_id": snapshot_id,
                        "node_id": node.id,
                        "node_type": node.node_type.value,
                        "canonical_name": node.canonical_name,
                        "symbol": node.symbol,
                        "external_ids": node.external_ids,
                        "metadata_": node.metadata,
                    }
                    for node in nodes
                ]
            )
            .on_conflict_do_nothing(
                index_elements=[GraphSnapshotNode.snapshot_id, GraphSnapshotNode.node_id]
            )
        )
        await self.session.execute(
            insert(GraphSnapshotEdge)
            .values(
                [
                    {
                        "snapshot_id": snapshot_id,
                        "edge_id": edge.id,
                        "source_node_id": edge.source_node_id,
                        "target_node_id": edge.target_node_id,
                        "relationship_type": edge.relationship_type.value,
                        "sign": edge.sign,
                        "weight": edge.weight,
                        "confidence": edge.confidence,
                        "provenance": edge.provenance,
                        "valid_from": edge.valid_from,
                        "valid_to": edge.valid_to,
                    }
                    for edge in edges
                ]
            )
            .on_conflict_do_nothing(
                index_elements=[GraphSnapshotEdge.snapshot_id, GraphSnapshotEdge.edge_id]
            )
        )
        row = await self.session.get(GraphSnapshot, snapshot_id)
        assert row is not None
        return GraphSnapshotValue(
            snapshot_id=row.snapshot_id,
            graph_version=row.graph_version,
            created_at=row.created_at,
            node_count=row.node_count,
            edge_count=row.edge_count,
            content_hash=row.content_hash,
            metadata=dict(row.metadata_ or {}),
        )

    async def list_snapshots(
        self, limit: int = 20, *, created_before: Any | None = None
    ) -> list[GraphSnapshotValue]:
        stmt = select(GraphSnapshot)
        if created_before is not None:
            stmt = stmt.where(GraphSnapshot.created_at <= created_before)
        rows = await self.session.execute(
            stmt.order_by(GraphSnapshot.created_at.desc(), GraphSnapshot.snapshot_id).limit(
                max(1, min(limit, 100))
            )
        )
        return [self._snapshot_value(row) for row in rows.scalars().all()]

    async def get_snapshot(
        self, snapshot_id: str | None = None
    ) -> tuple[GraphSnapshotValue, list[GraphNodeValue], list[GraphEdgeValue]] | None:
        snapshot_stmt = select(GraphSnapshot).order_by(
            GraphSnapshot.created_at.desc(), GraphSnapshot.snapshot_id
        )
        if snapshot_id:
            snapshot_stmt = select(GraphSnapshot).where(GraphSnapshot.snapshot_id == snapshot_id)
        snapshot = (await self.session.execute(snapshot_stmt.limit(1))).scalar_one_or_none()
        if snapshot is None:
            return None
        node_rows = await self.session.execute(
            select(GraphSnapshotNode)
            .where(GraphSnapshotNode.snapshot_id == snapshot.snapshot_id)
            .order_by(GraphSnapshotNode.node_id)
        )
        edge_rows = await self.session.execute(
            select(GraphSnapshotEdge)
            .where(GraphSnapshotEdge.snapshot_id == snapshot.snapshot_id)
            .order_by(GraphSnapshotEdge.edge_id)
        )
        return (
            self._snapshot_value(snapshot),
            [_node_value(row) for row in node_rows.scalars().all()],
            [_edge_value(row) for row in edge_rows.scalars().all()],
        )

    async def get_node(self, snapshot_id: str, node_id: str) -> GraphNodeValue | None:
        row = await self.session.execute(
            select(GraphSnapshotNode).where(
                GraphSnapshotNode.snapshot_id == snapshot_id, GraphSnapshotNode.node_id == node_id
            )
        )
        item = row.scalar_one_or_none()
        return _node_value(item) if item else None

    async def get_edge(self, snapshot_id: str, edge_id: str) -> GraphEdgeValue | None:
        row = await self.session.execute(
            select(GraphSnapshotEdge).where(
                GraphSnapshotEdge.snapshot_id == snapshot_id, GraphSnapshotEdge.edge_id == edge_id
            )
        )
        item = row.scalar_one_or_none()
        return _edge_value(item) if item else None

    async def neighbors(
        self, snapshot_id: str, node_id: str
    ) -> tuple[list[GraphNodeValue], list[GraphEdgeValue]]:
        rows = await self.session.execute(
            select(GraphSnapshotEdge)
            .where(
                GraphSnapshotEdge.snapshot_id == snapshot_id,
                (GraphSnapshotEdge.source_node_id == node_id)
                | (GraphSnapshotEdge.target_node_id == node_id),
            )
            .order_by(GraphSnapshotEdge.edge_id)
        )
        edges = [_edge_value(row) for row in rows.scalars().all()]
        ids = {node_id}
        for edge in edges:
            ids.update((edge.source_node_id, edge.target_node_id))
        node_rows = await self.session.execute(
            select(GraphSnapshotNode)
            .where(
                GraphSnapshotNode.snapshot_id == snapshot_id,
                GraphSnapshotNode.node_id.in_(sorted(ids)),
            )
            .order_by(GraphSnapshotNode.node_id)
        )
        return [_node_value(row) for row in node_rows.scalars().all()], edges

    @staticmethod
    def _snapshot_value(row: GraphSnapshot) -> GraphSnapshotValue:
        return GraphSnapshotValue(
            snapshot_id=row.snapshot_id,
            graph_version=row.graph_version,
            created_at=row.created_at,
            node_count=row.node_count,
            edge_count=row.edge_count,
            content_hash=row.content_hash,
            metadata=dict(row.metadata_ or {}),
        )
