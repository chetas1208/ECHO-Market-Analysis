from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Numeric, Text, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class MarketObservation(Base):
    """One OHLCV bar. Appends are idempotent via UNIQUE(symbol, timestamp, source, timeframe)."""

    __tablename__ = "market_observations"
    __table_args__ = (
        UniqueConstraint(
            "symbol",
            "timestamp",
            "source",
            "timeframe",
            name="uq_market_observations_symbol_timestamp_source_timeframe",
        ),
        Index("ix_market_observations_symbol_timestamp", "symbol", "timestamp"),
        Index(
            "ix_market_observations_symbol_timeframe_timestamp_desc",
            "symbol",
            "timeframe",
            text("timestamp DESC"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    open: Mapped[float] = mapped_column(Numeric(asdecimal=False), nullable=False)
    high: Mapped[float] = mapped_column(Numeric(asdecimal=False), nullable=False)
    low: Mapped[float] = mapped_column(Numeric(asdecimal=False), nullable=False)
    close: Mapped[float] = mapped_column(Numeric(asdecimal=False), nullable=False)
    volume: Mapped[float] = mapped_column(Numeric(asdecimal=False), nullable=False)
    vwap: Mapped[float | None] = mapped_column(Numeric(asdecimal=False))
    trade_count: Mapped[int | None] = mapped_column(BigInteger)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    timeframe: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'1m'"))
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
