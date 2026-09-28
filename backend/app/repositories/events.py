"""Persistence for canonical events. All SQL for events lives here."""

from __future__ import annotations

from collections.abc import Collection
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CanonicalEvent


class EventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def insert(self, values: dict[str, Any]) -> CanonicalEvent | None:
        """Insert an event; returns None when the id already exists (no exception)."""
        stmt = (
            insert(CanonicalEvent)
            .values(**values)
            .on_conflict_do_nothing(index_elements=[CanonicalEvent.id])
            .returning(CanonicalEvent)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get(self, event_id: str) -> CanonicalEvent | None:
        return await self.session.get(CanonicalEvent, event_id)

    async def exists(self, event_id: str) -> bool:
        stmt = select(func.count()).select_from(CanonicalEvent).where(CanonicalEvent.id == event_id)
        return (await self.session.execute(stmt)).scalar_one() > 0

    async def list(
        self,
        limit: int,
        offset: int,
        source_type: str | None = None,
        event_type: str | None = None,
        severity_min: float | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        event_types: Collection[str] | None = None,
    ) -> tuple[list[CanonicalEvent], int]:
        """Newest timestamp first; ties broken by id ascending for stable paging.

        All filters are optional and ANDed; ``total`` is the count of the filtered set.
        ``source_type`` (any case; stored uppercase) and ``event_type`` are exact matches;
        ``event_types`` matches any of the given values (an empty collection matches nothing);
        ``severity_min`` is inclusive; ``start``/``end`` bound ``timestamp`` inclusively.
        """
        conditions = []
        if source_type is not None:
            conditions.append(CanonicalEvent.source_type == source_type.upper())
        if event_type is not None:
            conditions.append(CanonicalEvent.event_type == event_type)
        if event_types is not None:
            conditions.append(CanonicalEvent.event_type.in_(sorted(event_types)))
        if severity_min is not None:
            conditions.append(CanonicalEvent.severity >= severity_min)
        if start is not None:
            conditions.append(CanonicalEvent.timestamp >= start)
        if end is not None:
            conditions.append(CanonicalEvent.timestamp <= end)
        rows = await self.session.execute(
            select(CanonicalEvent)
            .where(*conditions)
            .order_by(CanonicalEvent.timestamp.desc(), CanonicalEvent.id.asc())
            .limit(limit)
            .offset(offset)
        )
        total = (
            await self.session.execute(
                select(func.count()).select_from(CanonicalEvent).where(*conditions)
            )
        ).scalar_one()
        return list(rows.scalars().all()), total

    async def list_cause_candidates(
        self,
        start: datetime,
        end: datetime,
        data_cutoff_at: datetime,
        *,
        exclude_event_id: str,
        limit: int = 25,
    ) -> list[CanonicalEvent]:
        """Return non-market canonical events visible at a declared cutoff."""
        bounded = max(1, min(int(limit), 100))
        rows = await self.session.execute(
            select(CanonicalEvent)
            .where(
                CanonicalEvent.id != exclude_event_id,
                CanonicalEvent.source_type != "MARKET",
                CanonicalEvent.timestamp >= start,
                CanonicalEvent.timestamp <= end,
                CanonicalEvent.ingested_at <= data_cutoff_at,
            )
            .order_by(CanonicalEvent.timestamp.desc(), CanonicalEvent.id.asc())
            .limit(bounded)
        )
        return list(rows.scalars().all())
