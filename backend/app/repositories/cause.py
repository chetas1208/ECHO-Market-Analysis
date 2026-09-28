"""Persistence for immutable Cause Engine investigations and cluster observations."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.cause.types import CauseCandidateScore, CauseInvestigationResult, ClusterShockValue
from app.models import CanonicalEvent, CauseCandidate, CauseInvestigation, ClusterShock


class CauseRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save_investigation(
        self,
        result: CauseInvestigationResult,
        *,
        shock_event_id: str,
    ) -> None:
        await self.session.execute(
            insert(CauseInvestigation)
            .values(
                investigation_id=result.investigation_id,
                market_shock_event_id=shock_event_id,
                graph_snapshot_id=result.graph_snapshot_id,
                data_cutoff_at=result.data_cutoff_at,
                mode=result.mode.value,
                status=result.status.value,
                engine_version=result.engine_version,
                config_version=result.config_version,
                config_hash=result.config_hash,
                candidate_count=len(result.candidates),
                metadata_=result.metadata,
            )
            .on_conflict_do_nothing(index_elements=[CauseInvestigation.investigation_id])
        )
        rows = [
            {
                "investigation_id": result.investigation_id,
                "candidate_event_id": candidate.event_id,
                "rank": rank,
                "cause_score": candidate.score,
                "temporal_score": candidate.temporal_score,
                "entity_score": candidate.entity_score,
                "economic_score": candidate.economic_score,
                "graph_score": candidate.graph_score,
                "market_score": candidate.market_score,
                "source_score": candidate.source_score,
                "directional_consistency": candidate.directional_consistency,
                "evidence": candidate.evidence,
                "graph_paths": candidate.graph_paths,
            }
            for rank, candidate in enumerate(result.candidates, start=1)
        ]
        if rows:
            await self.session.execute(
                insert(CauseCandidate)
                .values(rows)
                .on_conflict_do_nothing(
                    index_elements=[
                        CauseCandidate.investigation_id,
                        CauseCandidate.candidate_event_id,
                    ]
                )
            )

    async def get_investigation(
        self, investigation_id: str
    ) -> tuple[CauseInvestigation, list[CauseCandidateScore], list[CanonicalEvent]] | None:
        investigation = await self.session.get(CauseInvestigation, investigation_id)
        if investigation is None:
            return None
        rows = await self.session.execute(
            select(CauseCandidate, CanonicalEvent)
            .join(CanonicalEvent, CanonicalEvent.id == CauseCandidate.candidate_event_id)
            .where(CauseCandidate.investigation_id == investigation_id)
            .order_by(CauseCandidate.rank.asc(), CauseCandidate.candidate_event_id.asc())
        )
        candidates: list[CauseCandidateScore] = []
        events: list[CanonicalEvent] = []
        for row, event in rows.all():
            candidates.append(
                CauseCandidateScore(
                    event_id=row.candidate_event_id,
                    title=event.title,
                    score=row.cause_score,
                    temporal_score=row.temporal_score,
                    entity_score=row.entity_score,
                    economic_score=row.economic_score,
                    graph_score=row.graph_score,
                    market_score=row.market_score,
                    source_score=row.source_score,
                    directional_consistency=row.directional_consistency,
                    evidence=list(row.evidence or []),
                    graph_paths=list(row.graph_paths or []),
                )
            )
            events.append(event)
        return investigation, candidates, events

    async def save_clusters(self, values: list[ClusterShockValue]) -> None:
        if not values:
            return
        await self.session.execute(
            insert(ClusterShock)
            .values(
                [
                    {
                        "cluster_id": value.cluster_id,
                        "cluster_key": value.cluster_key,
                        "as_of": value.as_of,
                        "direction": value.direction,
                        "members": value.members,
                        "member_count": value.member_count,
                        "abnormal_count": value.abnormal_count,
                        "strength": value.strength,
                        "synchronization": value.synchronization,
                        "volume_confirmation": value.volume_confirmation,
                        "graph_connectivity": value.graph_connectivity,
                        "source_event_id": value.source_event_id,
                        "metadata_": value.metadata,
                    }
                    for value in values
                ]
            )
            .on_conflict_do_nothing(index_elements=[ClusterShock.cluster_id])
        )

    async def list_clusters(
        self, *, start: datetime | None = None, end: datetime | None = None, limit: int = 100
    ) -> list[ClusterShockValue]:
        stmt = select(ClusterShock)
        if start is not None:
            stmt = stmt.where(ClusterShock.as_of >= start)
        if end is not None:
            stmt = stmt.where(ClusterShock.as_of <= end)
        rows = await self.session.execute(
            stmt.order_by(ClusterShock.as_of.desc(), ClusterShock.cluster_id.asc()).limit(
                max(1, min(limit, 500))
            )
        )
        return [
            ClusterShockValue(
                cluster_id=row.cluster_id,
                cluster_key=row.cluster_key,
                as_of=row.as_of,
                direction=row.direction,
                members=list(row.members or []),
                member_count=row.member_count,
                abnormal_count=row.abnormal_count,
                strength=row.strength,
                synchronization=row.synchronization,
                volume_confirmation=row.volume_confirmation,
                graph_connectivity=row.graph_connectivity,
                source_event_id=row.source_event_id,
                metadata=dict(row.metadata_ or {}),
            )
            for row in rows.scalars().all()
        ]
