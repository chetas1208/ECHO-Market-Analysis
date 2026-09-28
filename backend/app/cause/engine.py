"""Deterministic bidirectional Cause Engine service."""

from __future__ import annotations

import hashlib
import logging
import math
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from app.cause.cluster import detect_clusters
from app.cause.scoring import (
    classify_candidates,
    direction_consistency,
    event_time,
    response_state,
    temporal_score,
    weighted_cause_score,
)
from app.cause.types import (
    CauseCandidateScore,
    CauseConfig,
    CauseInvestigationResult,
    CauseMode,
    ClusterShockValue,
    ObservedShock,
)
from app.core.errors import CauseDependencyError, GraphSnapshotError, NotFoundError
from app.graph.propagation import PropagationConfig
from app.graph.service import ShockGraphService
from app.graph.types import GraphNodeType, RelationshipType
from app.models import CanonicalEvent
from app.repositories.cause import CauseRepository
from app.repositories.events import EventRepository
from app.repositories.market_events import MarketEventRepository

logger = logging.getLogger("echo.cause")


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _finite(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _metadata(event: CanonicalEvent) -> dict[str, Any]:
    value = event.metadata_
    return dict(value) if isinstance(value, dict) else {}


def _shock_direction(event: CanonicalEvent) -> str | None:
    value = _metadata(event).get("direction")
    return str(value) if value is not None else None


def _shock_symbol(event: CanonicalEvent) -> str | None:
    if event.companies:
        return str(event.companies[0]).strip().upper() or None
    value = _metadata(event).get("symbol")
    return str(value).strip().upper() if value else None


def _shock_residual_z(event: CanonicalEvent) -> float | None:
    metadata = _metadata(event)
    return _finite(metadata.get("sector_residual_z")) or _finite(metadata.get("market_residual_z"))


def observed_shock(event: CanonicalEvent) -> ObservedShock | None:
    symbol = _shock_symbol(event)
    direction = _shock_direction(event)
    if not symbol or not direction:
        return None
    metadata = _metadata(event)
    return ObservedShock(
        event_id=event.id,
        symbol=symbol,
        timestamp=_utc(event.timestamp),
        direction=direction,
        residual_z=_shock_residual_z(event),
        volume_z=_finite(metadata.get("volume_z")),
        shock_score=_finite(metadata.get("shock_score")),
        sector=str(metadata["sector_benchmark"]) if metadata.get("sector_benchmark") else None,
    )


def _event_terms(event: CanonicalEvent) -> set[str]:
    values = [*(event.companies or []), *(event.entities or []), *(event.locations or [])]
    return {"".join(char for char in str(value).casefold() if char.isalnum()) for value in values}


def _source_score(event: CanonicalEvent) -> float:
    independent = min(max(float(event.independent_source_count), 0.0) / 2.0, 1.0)
    return round(
        min(
            max(
                0.5 * float(event.confidence)
                + 0.3 * float(event.corroboration)
                + 0.2 * independent,
                0.0,
            ),
            1.0,
        ),
        6,
    )


def _entity_score(event: CanonicalEvent, projection: Any, symbol: str | None) -> float:
    if not symbol:
        return 0.0
    terms = _event_terms(event)
    target = next(
        (
            node
            for node in projection.nodes
            if node.node_type == GraphNodeType.COMPANY and node.symbol == symbol
        ),
        None,
    )
    if target is None:
        return 0.0
    aliases = {
        "".join(char for char in value.casefold() if char.isalnum())
        for value in (target.symbol or "", target.canonical_name)
    }
    if any(
        alias and (alias in terms or any(term.startswith(alias) for term in terms))
        for alias in aliases
    ):
        return 1.0
    path_terms = {
        "".join(char for char in node.canonical_name.casefold() if char.isalnum())
        for node in projection.nodes
        if node.node_type != GraphNodeType.CHANNEL
    }
    return 0.5 if terms & path_terms else 0.0


def _target_exposure(projection: Any, symbol: str | None) -> Any | None:
    if not symbol:
        return None
    return next((item for item in projection.companies if item.symbol.upper() == symbol), None)


def _market_score(
    projection: Any,
    observed: dict[str, list[ObservedShock]],
    shock_at: datetime,
) -> float:
    if not projection.companies:
        return 0.0
    matches: list[float] = []
    for exposure in projection.companies:
        options = observed.get(exposure.symbol.upper(), [])
        if not options:
            continue
        option = sorted(
            options,
            key=lambda item: (abs((item.timestamp - shock_at).total_seconds()), item.event_id),
        )[0]
        consistency = direction_consistency(exposure.exposure, option.direction)
        matches.append(1.0 if consistency > 0 else 0.0)
    if not matches:
        return 0.0
    agreement = sum(matches) / len(matches)
    coverage = min(len(matches) / min(len(projection.companies), 4), 1.0)
    return round(0.7 * agreement + 0.3 * coverage, 6)


def _investigation_id(
    shock_event_id: str, snapshot_id: str, mode: CauseMode, cutoff: datetime, config_hash: str
) -> str:
    raw = "|".join((shock_event_id, snapshot_id, mode.value, cutoff.isoformat(), config_hash))
    return f"ci_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:20]}"


class CauseEngine:
    def __init__(self, session: Any, *, config: CauseConfig | None = None) -> None:
        self.session = session
        self.config = config or CauseConfig()
        self.events = EventRepository(session)
        self.market_events = MarketEventRepository(session)
        self.cause_repository = CauseRepository(session)
        self.graph = ShockGraphService(session)

    @staticmethod
    def _result_from_row(
        row: Any, candidates: list[CauseCandidateScore]
    ) -> CauseInvestigationResult:
        return CauseInvestigationResult(
            investigation_id=row.investigation_id,
            shock_event_id=row.market_shock_event_id,
            graph_snapshot_id=row.graph_snapshot_id,
            created_at=row.created_at,
            data_cutoff_at=row.data_cutoff_at,
            mode=CauseMode(row.mode),
            status=row.status,
            engine_version=row.engine_version,
            config_version=row.config_version,
            config_hash=row.config_hash,
            candidates=candidates,
            metadata=dict(row.metadata_ or {}),
        )

    async def _snapshot_id(
        self,
        *,
        cutoff: datetime,
        mode: CauseMode,
        requested: str | None,
    ) -> str:
        if requested:
            loaded = await self.graph.load_snapshot(requested)
            if mode == CauseMode.REALTIME and _utc(loaded[0].created_at) > cutoff:
                raise GraphSnapshotError(
                    "Requested graph snapshot was created after the realtime cutoff"
                )
            return loaded[0].snapshot_id
        snapshots = await self.graph.list_snapshots(
            100, created_before=cutoff if mode == CauseMode.REALTIME else None
        )
        if not snapshots:
            raise CauseDependencyError("No graph snapshot is available at the investigation cutoff")
        return snapshots[0].snapshot_id

    async def investigate_market_shock(
        self,
        shock_event_id: str,
        *,
        mode: CauseMode = CauseMode.REALTIME,
        data_cutoff_at: datetime | None = None,
        snapshot_id: str | None = None,
    ) -> CauseInvestigationResult:
        started = time.perf_counter()
        shock = await self.events.get(shock_event_id)
        if shock is None:
            raise NotFoundError(f"Event '{shock_event_id}' not found")
        if shock.source_type != "MARKET" or shock.event_type != "market_shock":
            raise CauseDependencyError("Cause investigation requires a MARKET market_shock event")
        shock_at = _utc(shock.timestamp)
        cutoff = _utc(data_cutoff_at or shock.ingested_at)
        if cutoff < shock_at:
            raise CauseDependencyError("data_cutoff_at cannot precede the market shock timestamp")
        mode = CauseMode(mode)
        graph_snapshot_id = await self._snapshot_id(cutoff=cutoff, mode=mode, requested=snapshot_id)
        investigation_id = _investigation_id(
            shock.id, graph_snapshot_id, mode, cutoff, self.config.hash()
        )
        existing = await self.cause_repository.get_investigation(investigation_id)
        if existing is not None:
            row, candidates, _ = existing
            return self._result_from_row(row, candidates)

        candidate_started = time.perf_counter()
        candidate_events = await self.events.list_cause_candidates(
            self.config.lookback_start(shock_at),
            min(self.config.lookahead_end(shock_at, mode), cutoff),
            cutoff,
            exclude_event_id=shock.id,
            limit=self.config.max_candidates,
        )
        candidate_duration_ms = round((time.perf_counter() - candidate_started) * 1000, 3)
        market_start = max(
            self.config.lookback_start(shock_at),
            shock_at - timedelta(minutes=self.config.market_pattern_window_minutes),
        )
        market_end = min(
            cutoff,
            shock_at + timedelta(minutes=self.config.market_pattern_window_minutes),
        )
        market_events = await self.market_events.list_market_shocks_between(
            market_start, market_end, data_cutoff_at=cutoff, limit=self.config.cluster_max_events
        )
        observed_by_symbol: dict[str, list[ObservedShock]] = {}
        for event in market_events:
            observed = observed_shock(event)
            if observed is not None:
                observed_by_symbol.setdefault(observed.symbol.upper(), []).append(observed)
        shock_observed = observed_shock(shock)
        if shock_observed is not None:
            observed_by_symbol.setdefault(shock_observed.symbol.upper(), []).append(shock_observed)

        candidates: list[CauseCandidateScore] = []
        observed_direction = _shock_direction(shock)
        tau_seconds = self.config.temporal_tau_hours * 3600
        for candidate in candidate_events:
            projection = await self.graph.project_event(
                candidate,
                snapshot_id=graph_snapshot_id,
                config=PropagationConfig(max_depth=3, max_results=25),
            )
            symbol = _shock_symbol(shock)
            target = _target_exposure(projection, symbol)
            exposure = float(target.exposure) if target is not None else 0.0
            confidence = float(target.confidence) if target is not None else 0.0
            consistency = direction_consistency(exposure, observed_direction)
            temporal = temporal_score(
                abs((event_time(candidate) - shock_at).total_seconds()), tau_seconds
            )
            economic = round(min(abs(exposure) * max(confidence, 0.0), 1.0), 6)
            graph_score = round(
                min(max(economic * ((consistency + 1.0) / 2.0 if consistency else 0.5), 0.0), 1.0),
                6,
            )
            market = _market_score(projection, observed_by_symbol, shock_at)
            entity = _entity_score(candidate, projection, symbol)
            source = _source_score(candidate)
            score = weighted_cause_score(
                {
                    "temporal": temporal,
                    "entity": entity,
                    "economic": economic,
                    "graph": graph_score,
                    "market": market,
                    "source": source,
                },
                self.config,
            )
            evidence: list[dict[str, Any]] = [
                {
                    "type": "temporal",
                    "candidate_at": event_time(candidate).isoformat(),
                    "shock_at": shock_at.isoformat(),
                    "delta_seconds": round(
                        abs((event_time(candidate) - shock_at).total_seconds()), 3
                    ),
                    "post_shock_evidence": event_time(candidate) > shock_at,
                },
                {
                    "type": "economic_channels",
                    "channels": dict(candidate.economic_channels or {}),
                },
                {
                    "type": "graph_compatibility",
                    "symbol": symbol,
                    "exposure": round(exposure, 6),
                    "confidence": round(confidence, 6),
                    "directional_consistency": consistency,
                },
                {
                    "type": "market_pattern",
                    "observed_symbols": sorted(observed_by_symbol),
                    "matched_score": market,
                },
                {
                    "type": "source_quality",
                    "confidence": float(candidate.confidence),
                    "corroboration": float(candidate.corroboration),
                    "independent_source_count": candidate.independent_source_count,
                },
            ]
            candidates.append(
                CauseCandidateScore(
                    event_id=candidate.id,
                    title=candidate.title,
                    score=score,
                    temporal_score=round(temporal, 6),
                    entity_score=round(entity, 6),
                    economic_score=economic,
                    graph_score=graph_score,
                    market_score=market,
                    source_score=source,
                    directional_consistency=consistency,
                    evidence=evidence[: self.config.max_evidence],
                    graph_paths=(
                        [path.model_dump(mode="json") for path in target.paths]
                        if target is not None
                        else []
                    ),
                )
            )
        candidates.sort(key=lambda item: (-item.score, -item.graph_score, item.event_id))
        candidates = candidates[: self.config.max_candidates]
        status = classify_candidates(candidates, self.config)
        result = CauseInvestigationResult(
            investigation_id=investigation_id,
            shock_event_id=shock.id,
            graph_snapshot_id=graph_snapshot_id,
            created_at=datetime.now(UTC),
            data_cutoff_at=cutoff,
            mode=mode,
            status=status,
            engine_version=self.config.engine_version,
            config_version=self.config.version,
            config_hash=self.config.hash(),
            candidates=candidates,
            metadata={
                "candidate_window_start": self.config.lookback_start(shock_at).isoformat(),
                "candidate_window_end": min(
                    self.config.lookahead_end(shock_at, mode), cutoff
                ).isoformat(),
                "shock_symbol": _shock_symbol(shock),
                "score_semantics": "evidence_compatibility_not_causal_probability",
            },
        )
        await self.cause_repository.save_investigation(result, shock_event_id=shock.id)
        await self.session.commit()
        logger.info(
            "investigation_%s",
            status.value.casefold(),
            extra={
                "operation": f"investigation_{status.value.casefold()}",
                "shock_event_id": shock.id,
                "candidate_count": len(candidates),
                "graph_snapshot_id": graph_snapshot_id,
                "cutoff": cutoff.isoformat(),
                "candidate_retrieval_duration_ms": candidate_duration_ms,
                "duration_ms": round((time.perf_counter() - started) * 1000, 3),
            },
        )
        persisted = await self.cause_repository.get_investigation(investigation_id)
        if persisted is None:
            return result
        row, persisted_candidates, _ = persisted
        return self._result_from_row(row, persisted_candidates)

    async def get_investigation(self, investigation_id: str) -> CauseInvestigationResult:
        found = await self.cause_repository.get_investigation(investigation_id)
        if found is None:
            raise NotFoundError(f"Investigation '{investigation_id}' not found")
        row, candidates, _ = found
        return self._result_from_row(row, candidates)

    async def detect_market_clusters(
        self,
        *,
        as_of: datetime,
        data_cutoff_at: datetime,
        snapshot_id: str,
    ) -> list[ClusterShockValue]:
        snapshot, nodes, edges = await self.graph.load_snapshot(snapshot_id)
        start = _utc(as_of) - timedelta(minutes=self.config.cluster_sync_minutes)
        events = await self.market_events.list_market_shocks_between(
            start,
            _utc(as_of),
            data_cutoff_at=_utc(data_cutoff_at),
            limit=self.config.cluster_max_events,
        )
        memberships: dict[str, set[str]] = {}
        for node in nodes:
            if node.node_type == GraphNodeType.COMPANY and node.symbol:
                sector = node.metadata.get("sector")
                if sector:
                    memberships.setdefault(node.symbol.upper(), set()).add(f"sector:{sector}")
        for edge in edges:
            if edge.relationship_type not in {
                RelationshipType.MEMBER_OF_SECTOR,
                RelationshipType.TECHNOLOGY_DEPENDENCY,
                RelationshipType.GEOGRAPHIC_EXPOSURE,
            }:
                continue
            target = next((node for node in nodes if node.id == edge.target_node_id), None)
            source = next((node for node in nodes if node.id == edge.source_node_id), None)
            if target and source and target.symbol:
                memberships.setdefault(target.symbol.upper(), set()).add(source.id)
        observed = [item for event in events if (item := observed_shock(event)) is not None]
        clusters = detect_clusters(
            observed,
            memberships,
            self.config,
            source_event_id=events[-1].id if events else None,
        )
        await self.cause_repository.save_clusters(clusters)
        await self.session.commit()
        logger.info(
            "cluster_shocks_detected",
            extra={
                "operation": "cluster_shocks_detected",
                "graph_snapshot_id": snapshot.snapshot_id,
                "cluster_count": len(clusters),
            },
        )
        return clusters

    async def analyze_world_event(
        self,
        event_id: str,
        *,
        data_cutoff_at: datetime | None = None,
        snapshot_id: str | None = None,
    ) -> dict[str, Any]:
        event = await self.events.get(event_id)
        if event is None:
            raise NotFoundError(f"Event '{event_id}' not found")
        cutoff = _utc(data_cutoff_at or event.ingested_at)
        graph_snapshot_id = await self._snapshot_id(
            cutoff=cutoff, mode=CauseMode.REALTIME, requested=snapshot_id
        )
        projection = await self.graph.project_event(
            event, snapshot_id=graph_snapshot_id, config=PropagationConfig(max_depth=3)
        )
        market_events = await self.market_events.list_market_shocks_between(
            _utc(event.timestamp), cutoff, data_cutoff_at=cutoff, limit=500
        )
        by_symbol: dict[str, list[ObservedShock]] = {}
        for market_event in market_events:
            item = observed_shock(market_event)
            if item is not None:
                by_symbol.setdefault(item.symbol.upper(), []).append(item)
        impacts: list[dict[str, Any]] = []
        for exposure in projection.companies:
            observations = by_symbol.get(exposure.symbol.upper(), [])
            observation = (
                sorted(observations, key=lambda item: (item.timestamp, item.event_id))[-1]
                if observations
                else None
            )
            residual = observation.residual_z if observation else None
            impacts.append(
                {
                    "symbol": exposure.symbol,
                    "exposure": exposure.exposure,
                    "confidence": exposure.confidence,
                    "actual_residual_z": residual,
                    "response_state": response_state(
                        exposure.exposure, residual, self.config
                    ).value,
                    "paths": [path.model_dump(mode="json") for path in exposure.paths],
                }
            )
        return {
            "event_id": event.id,
            "graph_snapshot_id": graph_snapshot_id,
            "graph_version": projection.graph_version,
            "data_cutoff_at": cutoff,
            "market_confirmation_unavailable": not bool(market_events),
            "companies": impacts,
            "unmapped_channels": projection.unmapped_channels,
        }
