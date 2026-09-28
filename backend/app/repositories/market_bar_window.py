"""Newest-first bar window ending at a given time (the bar repository only pages from the past)."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.market.types import Bar, Interval
from app.models.market import MarketObservation
from app.repositories.market import MAX_BARS_LIMIT, _to_bar


async def bars_ending_at(
    session: AsyncSession, symbol: str, interval: Interval, end: datetime, n: int
) -> list[Bar]:
    """The newest ``n`` (capped at 2000) rows with ``timestamp <= end``, ascending."""
    n = max(1, min(int(n), MAX_BARS_LIMIT))
    stmt = (
        select(MarketObservation)
        .where(
            MarketObservation.symbol == symbol.strip().upper(),
            MarketObservation.timeframe == Interval(interval).value,
            MarketObservation.timestamp <= end,
        )
        .order_by(MarketObservation.timestamp.desc(), MarketObservation.source.desc())
        .limit(n)
    )
    rows = (await session.execute(stmt)).scalars().all()
    return [_to_bar(r) for r in reversed(rows)]
