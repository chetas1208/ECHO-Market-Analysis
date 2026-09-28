"""Persistence for market bars (market_observations). All SQL for bars lives here."""

from collections.abc import Iterator, Sequence
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.market.types import Bar, Interval, ProviderName
from app.models.market import MarketObservation

MAX_BARS_LIMIT = 2000
UPSERT_CHUNK_SIZE = 1000  # 1000 rows x 12 params stays far below asyncpg's 32767 limit

_CONFLICT_COLS = ("symbol", "timestamp", "source", "timeframe")
_UPDATE_COLS = ("open", "high", "low", "close", "volume", "vwap", "trade_count", "received_at")


def _to_row(bar: Bar) -> dict[str, object]:
    return {
        "symbol": bar.symbol,
        "timestamp": bar.timestamp,
        "timeframe": bar.interval.value,
        "source": bar.source.value,
        "open": bar.open,
        "high": bar.high,
        "low": bar.low,
        "close": bar.close,
        "volume": bar.volume,
        "vwap": bar.vwap,
        "trade_count": bar.trade_count,
        "received_at": bar.received_at,
    }


def _to_bar(row: MarketObservation) -> Bar:
    return Bar(
        symbol=row.symbol,
        timestamp=row.timestamp,
        interval=Interval(row.timeframe),
        open=row.open,
        high=row.high,
        low=row.low,
        close=row.close,
        volume=row.volume,
        vwap=row.vwap,
        trade_count=row.trade_count,
        source=ProviderName(row.source),
        received_at=row.received_at,
    )


def _chunks(rows: list[dict[str, object]], size: int) -> Iterator[list[dict[str, object]]]:
    for i in range(0, len(rows), size):
        yield rows[i : i + size]


class MarketBarRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert_bars(self, bars: Sequence[Bar]) -> int:
        """Insert bars; on (symbol, timestamp, source, timeframe) conflict update the values.

        Duplicate keys inside ``bars`` collapse to the last occurrence (Postgres cannot
        upsert the same key twice in one statement). Returns rows inserted or updated.
        The caller owns the transaction (commit).
        """
        if not bars:
            return 0
        deduped: dict[tuple[str, datetime, str, str], dict[str, object]] = {}
        for bar in bars:
            row = _to_row(bar)
            deduped[(bar.symbol, bar.timestamp, bar.source.value, bar.interval.value)] = row
        affected = 0
        for chunk in _chunks(list(deduped.values()), UPSERT_CHUNK_SIZE):
            stmt = insert(MarketObservation).values(chunk)
            stmt = stmt.on_conflict_do_update(
                index_elements=list(_CONFLICT_COLS),
                set_={c: getattr(stmt.excluded, c) for c in _UPDATE_COLS},
            )
            result = await self.session.execute(stmt)
            affected += result.rowcount or 0
        return affected

    async def get_bars(
        self,
        symbol: str,
        interval: Interval,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 500,
    ) -> list[Bar]:
        """Ascending bars with ``start <= timestamp <= end``; limit clamped to 1..2000."""
        limit = max(1, min(int(limit), MAX_BARS_LIMIT))
        stmt = select(MarketObservation).where(
            MarketObservation.symbol == symbol.strip().upper(),
            MarketObservation.timeframe == Interval(interval).value,
        )
        if start is not None:
            stmt = stmt.where(MarketObservation.timestamp >= start)
        if end is not None:
            stmt = stmt.where(MarketObservation.timestamp <= end)
        stmt = stmt.order_by(MarketObservation.timestamp.asc(), MarketObservation.source.asc())
        rows = (await self.session.execute(stmt.limit(limit))).scalars().all()
        return [_to_bar(r) for r in rows]

    async def load_recent(self, symbol: str, interval: Interval, n: int) -> list[Bar]:
        """The most recent ``n`` bars (capped at 2000), returned in ascending order."""
        n = max(0, min(int(n), MAX_BARS_LIMIT))
        if n == 0:
            return []
        stmt = (
            select(MarketObservation)
            .where(
                MarketObservation.symbol == symbol.strip().upper(),
                MarketObservation.timeframe == Interval(interval).value,
            )
            .order_by(MarketObservation.timestamp.desc(), MarketObservation.source.desc())
            .limit(n)
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return [_to_bar(r) for r in reversed(rows)]

    async def latest_timestamp(self, symbol: str | None = None) -> datetime | None:
        stmt = select(func.max(MarketObservation.timestamp))
        if symbol is not None:
            stmt = stmt.where(MarketObservation.symbol == symbol.strip().upper())
        return (await self.session.execute(stmt)).scalar_one_or_none()
