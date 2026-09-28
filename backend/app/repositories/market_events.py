"""Read-side queries for market-originated canonical events (source_type=MARKET)."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CanonicalEvent

MARKET_SOURCE_TYPE = "MARKET"  # stored uppercase in the database
MARKET_SHOCK_EVENT_TYPE = "market_shock"


class MarketEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_market_shocks(self, limit: int) -> list[CanonicalEvent]:
        """Market shock events, newest timestamp first (ties by id ascending)."""
        stmt = (
            select(CanonicalEvent)
            .where(
                CanonicalEvent.source_type == MARKET_SOURCE_TYPE,
                CanonicalEvent.event_type == MARKET_SHOCK_EVENT_TYPE,
            )
            .order_by(CanonicalEvent.timestamp.desc(), CanonicalEvent.id.asc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_market_shocks_between(
        self,
        start: datetime,
        end: datetime,
        *,
        data_cutoff_at: datetime,
        limit: int = 200,
    ) -> list[CanonicalEvent]:
        bounded = max(1, min(int(limit), 1000))
        stmt = (
            select(CanonicalEvent)
            .where(
                CanonicalEvent.source_type == MARKET_SOURCE_TYPE,
                CanonicalEvent.event_type == MARKET_SHOCK_EVENT_TYPE,
                CanonicalEvent.timestamp >= start,
                CanonicalEvent.timestamp <= end,
                CanonicalEvent.ingested_at <= data_cutoff_at,
            )
            .order_by(CanonicalEvent.timestamp.asc(), CanonicalEvent.id.asc())
            .limit(bounded)
        )
        return list((await self.session.execute(stmt)).scalars().all())
