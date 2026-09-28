"""ShockGraph application service: snapshot integrity, event projection, and cache."""

from __future__ import annotations

import logging
import time
from collections import OrderedDict
from typing import Any

from app.core.errors import GraphSnapshotError, NotFoundError
from app.graph.propagation import PropagationConfig, propagate
from app.graph.repository import GraphRepository, graph_content_hash
from app.graph.seed import load_seed
from app.graph.types import (
    GraphEdgeValue,
    GraphNodeType,
    GraphNodeValue,
    GraphProjection,
    GraphSnapshotValue,
)
from app.models import CanonicalEvent

logger = logging.getLogger("echo.graph.service")


class ShockGraphService:
    def __init__(self, session: Any, *, cache_size: int = 4) -> None:
        self.session = session
        self.repository = GraphRepository(session)
        self._cache_size = max(1, cache_size)
        self._cache: OrderedDict[
            str, tuple[GraphSnapshotValue, list[GraphNodeValue], list[GraphEdgeValue]]
        ] = OrderedDict()

    async def create_seed_snapshot(self) -> GraphSnapshotValue:
        snapshot = await self.repository.create_snapshot(load_seed())
        await self.session.commit()
        self._cache.pop(snapshot.snapshot_id, None)
        logger.info(
            "graph_snapshot_created",
            extra={
                "operation": "graph_snapshot_created",
                "snapshot_id": snapshot.snapshot_id,
                "node_count": snapshot.node_count,
                "edge_count": snapshot.edge_count,
            },
        )
        return snapshot

    async def list_snapshots(
        self, limit: int = 20, *, created_before: Any | None = None
    ) -> list[GraphSnapshotValue]:
        return await self.repository.list_snapshots(limit, created_before=created_before)

    async def load_snapshot(
        self, snapshot_id: str | None = None
    ) -> tuple[GraphSnapshotValue, list[GraphNodeValue], list[GraphEdgeValue]]:
        key = snapshot_id or "__latest__"
        if key in self._cache:
            value = self._cache.pop(key)
            self._cache[key] = value
            return value
        loaded = await self.repository.get_snapshot(snapshot_id)
        if loaded is None:
            raise NotFoundError("Graph snapshot not found")
        snapshot, nodes, edges = loaded
        if graph_content_hash(nodes, edges) != snapshot.content_hash:
            logger.error(
                "graph_snapshot_integrity_failed",
                extra={
                    "operation": "graph_snapshot_integrity_failed",
                    "snapshot_id": snapshot.snapshot_id,
                },
            )
            raise GraphSnapshotError(
                f"Graph snapshot '{snapshot.snapshot_id}' failed integrity verification"
            )
        actual = (snapshot, nodes, edges)
        self._cache[key] = actual
        self._cache[snapshot.snapshot_id] = actual
        while len(self._cache) > self._cache_size * 2:
            self._cache.popitem(last=False)
        logger.info(
            "graph_snapshot_loaded",
            extra={
                "operation": "graph_snapshot_loaded",
                "snapshot_id": snapshot.snapshot_id,
                "node_count": snapshot.node_count,
                "edge_count": snapshot.edge_count,
            },
        )
        return actual

    async def node(self, node_id: str, snapshot_id: str | None = None) -> GraphNodeValue:
        _snapshot, nodes, _ = await self.load_snapshot(snapshot_id)
        value = next((node for node in nodes if node.id == node_id), None)
        if value is None:
            raise NotFoundError(f"Graph node '{node_id}' not found")
        return value

    async def edge(self, edge_id: str, snapshot_id: str | None = None) -> GraphEdgeValue:
        _, _, edges = await self.load_snapshot(snapshot_id)
        value = next((edge for edge in edges if edge.id == edge_id), None)
        if value is None:
            raise NotFoundError(f"Graph edge '{edge_id}' not found")
        return value

    async def neighbors(
        self, node_id: str, snapshot_id: str | None = None
    ) -> tuple[GraphSnapshotValue, list[GraphNodeValue], list[GraphEdgeValue]]:
        snapshot, _, _ = await self.load_snapshot(snapshot_id)
        nodes, edges = await self.repository.neighbors(snapshot.snapshot_id, node_id)
        if not nodes:
            raise NotFoundError(f"Graph node '{node_id}' not found")
        return snapshot, nodes, edges

    async def project_event(
        self,
        event: CanonicalEvent,
        *,
        snapshot_id: str | None = None,
        config: PropagationConfig | None = None,
    ) -> GraphProjection:
        started = time.perf_counter()
        snapshot, nodes, edges = await self.load_snapshot(snapshot_id)
        node_map = {node.id: node for node in nodes}
        strengths: dict[str, float] = {}
        unmapped: list[str] = []
        for channel, value in sorted((event.economic_channels or {}).items()):
            node_id = f"channel:{channel}"
            if node_id not in node_map:
                unmapped.append(channel)
                logger.info(
                    "unmapped_channel",
                    extra={
                        "operation": "unmapped_channel",
                        "event_id": event.id,
                        "channel": channel,
                    },
                )
                continue
            strengths[node_id] = float(value)

        aliases = {
            str(node.symbol).casefold(): node.id
            for node in nodes
            if node.node_type == GraphNodeType.COMPANY and node.symbol
        }
        aliases.update(
            {
                node.canonical_name.casefold(): node.id
                for node in nodes
                if node.node_type == GraphNodeType.COMPANY
            }
        )
        direct_ids = [
            aliases[str(company).strip().casefold()]
            for company in (event.companies or [])
            if str(company).strip().casefold() in aliases
        ]
        companies = propagate(
            channel_strengths=strengths,
            event_confidence=float(event.confidence),
            nodes=nodes,
            edges=edges,
            direct_company_ids=direct_ids,
            config=config,
        )
        used_nodes = {node_id for node_id in strengths}
        used_edges: set[str] = set()
        for company in companies:
            for path in company.paths:
                used_nodes.update(path.nodes)
                used_edges.update(path.edge_ids)
        projection_nodes = [node for node in nodes if node.id in used_nodes]
        projection_edges = [edge for edge in edges if edge.id in used_edges]
        duration_ms = round((time.perf_counter() - started) * 1000, 3)
        result = GraphProjection(
            event_id=event.id,
            graph_snapshot_id=snapshot.snapshot_id,
            graph_version=snapshot.graph_version,
            nodes=projection_nodes,
            edges=projection_edges,
            companies=companies,
            unmapped_channels=unmapped,
            diagnostics={
                "status": "no_exposure_found" if not companies else "ok",
                "channel_count": len(strengths),
                "unmapped_channel_count": len(unmapped),
            },
        )
        logger.info(
            "exposure_ranked",
            extra={
                "operation": "exposure_ranked",
                "event_id": event.id,
                "snapshot_id": snapshot.snapshot_id,
                "company_count": len(companies),
                "duration_ms": duration_ms,
            },
        )
        return result
