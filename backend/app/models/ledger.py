"""Append-only Day 7 actual, evaluation, simulation, and portfolio records."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ForecastActual(Base):
    __tablename__ = "forecast_actuals"
    __table_args__ = (
        CheckConstraint("length(btrim(symbol)) > 0", name="symbol_nonempty"),
        CheckConstraint("horizon IN ('INTRADAY', '1D', '2D', '5D', '10D', '20D')", name="horizon"),
        CheckConstraint("length(btrim(source)) > 0", name="source_nonempty"),
        UniqueConstraint(
            "forecast_run_id",
            "horizon",
            "market_timestamp",
            name="uq_forecast_actuals_run_horizon_timestamp",
        ),
        UniqueConstraint("observation_hash", name="uq_forecast_actuals_observation_hash"),
        Index("ix_forecast_actuals_run_observed_at", "forecast_run_id", "observed_at"),
        Index("ix_forecast_actuals_symbol_market_timestamp", "symbol", "market_timestamp"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    forecast_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("forecast_runs.id", ondelete="RESTRICT"), nullable=False
    )
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    horizon: Mapped[str] = mapped_column(Text, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    market_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actual_price: Mapped[float | None] = mapped_column(Numeric(asdecimal=False))
    actual_return: Mapped[float | None] = mapped_column(Numeric(asdecimal=False))
    actual_abnormal_return: Mapped[float | None] = mapped_column(Numeric(asdecimal=False))
    market_return: Mapped[float | None] = mapped_column(Numeric(asdecimal=False))
    sector_return: Mapped[float | None] = mapped_column(Numeric(asdecimal=False))
    source: Mapped[str] = mapped_column(Text, nullable=False)
    observation_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ForecastEvaluation(Base):
    __tablename__ = "forecast_evaluations"
    __table_args__ = (
        CheckConstraint("horizon IN ('1D', '2D', '5D', '10D', '20D')", name="horizon"),
        CheckConstraint(
            "status IN ('PENDING', 'PARTIAL', 'COMPLETE', 'UNAVAILABLE')", name="status"
        ),
        CheckConstraint(
            "probability_positive IS NULL OR probability_positive BETWEEN 0 AND 1",
            name="probability_unit",
        ),
        UniqueConstraint("evaluation_hash", name="uq_forecast_evaluations_hash"),
        Index("ix_forecast_evaluations_run_horizon", "forecast_run_id", "horizon"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    forecast_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("forecast_runs.id", ondelete="RESTRICT"), nullable=False
    )
    horizon: Mapped[str] = mapped_column(Text, nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    predicted_q10: Mapped[float | None] = mapped_column(Numeric(asdecimal=False))
    predicted_q50: Mapped[float | None] = mapped_column(Numeric(asdecimal=False))
    predicted_q90: Mapped[float | None] = mapped_column(Numeric(asdecimal=False))
    probability_positive: Mapped[float | None] = mapped_column(Numeric(asdecimal=False))
    actual_abnormal_return: Mapped[float | None] = mapped_column(Numeric(asdecimal=False))
    absolute_error: Mapped[float | None] = mapped_column(Numeric(asdecimal=False))
    squared_error: Mapped[float | None] = mapped_column(Numeric(asdecimal=False))
    directional_correct: Mapped[bool | None] = mapped_column()
    interval_covered: Mapped[bool | None] = mapped_column()
    pinball_q10: Mapped[float | None] = mapped_column(Numeric(asdecimal=False))
    pinball_q50: Mapped[float | None] = mapped_column(Numeric(asdecimal=False))
    pinball_q90: Mapped[float | None] = mapped_column(Numeric(asdecimal=False))
    brier_contribution: Mapped[float | None] = mapped_column(Numeric(asdecimal=False))
    evaluation_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SimulatedTrade(Base):
    __tablename__ = "simulated_trades"
    __table_args__ = (
        CheckConstraint("length(btrim(symbol)) > 0", name="symbol_nonempty"),
        CheckConstraint("side IN ('LONG', 'SHORT', 'NO_TRADE')", name="side"),
        CheckConstraint("planned_exit_horizon IN ('1D', '2D', '5D', '10D', '20D')", name="horizon"),
        CheckConstraint("position_size >= 0", name="size_nonnegative"),
        CheckConstraint("notional >= 0", name="notional_nonnegative"),
        CheckConstraint("hedge_ratio >= 0", name="hedge_ratio_nonnegative"),
        CheckConstraint(
            "status IN ('PLANNED', 'OPEN', 'CLOSED', 'STOPPED', 'EXPIRED', "
            "'CANCELLED_BEFORE_ENTRY', 'NO_TRADE')",
            name="status",
        ),
        CheckConstraint("jsonb_typeof(metadata) = 'object'", name="metadata_object"),
        UniqueConstraint("plan_hash", name="uq_simulated_trades_plan_hash"),
        Index("ix_simulated_trades_forecast_run_id", "forecast_run_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    forecast_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("forecast_runs.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    side: Mapped[str] = mapped_column(Text, nullable=False)
    decision_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    entry_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    entry_price: Mapped[float | None] = mapped_column(Numeric(asdecimal=False))
    planned_exit_horizon: Mapped[str] = mapped_column(Text, nullable=False)
    planned_exit_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    position_size: Mapped[float] = mapped_column(
        Numeric(asdecimal=False), nullable=False, server_default=text("0")
    )
    notional: Mapped[float] = mapped_column(
        Numeric(asdecimal=False), nullable=False, server_default=text("0")
    )
    hedge_symbol: Mapped[str | None] = mapped_column(Text)
    hedge_ratio: Mapped[float] = mapped_column(
        Numeric(asdecimal=False), nullable=False, server_default=text("0")
    )
    stop_type: Mapped[str | None] = mapped_column(Text)
    stop_value: Mapped[float | None] = mapped_column(Numeric(asdecimal=False))
    take_profit: Mapped[float | None] = mapped_column(Numeric(asdecimal=False))
    strategy_version: Mapped[str] = mapped_column(Text, nullable=False)
    config_hash: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    gross_pnl: Mapped[float] = mapped_column(
        Numeric(asdecimal=False), nullable=False, server_default=text("0")
    )
    costs: Mapped[float] = mapped_column(
        Numeric(asdecimal=False), nullable=False, server_default=text("0")
    )
    hedge_pnl: Mapped[float] = mapped_column(
        Numeric(asdecimal=False), nullable=False, server_default=text("0")
    )
    net_pnl: Mapped[float] = mapped_column(
        Numeric(asdecimal=False), nullable=False, server_default=text("0")
    )
    return_on_allocated_capital: Mapped[float | None] = mapped_column(Numeric(asdecimal=False))
    plan_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )


class SimulatedTradeEvent(Base):
    __tablename__ = "simulated_trade_events"
    __table_args__ = (
        CheckConstraint(
            "state IN ('PLANNED', 'OPEN', 'CLOSED', 'STOPPED', 'EXPIRED', "
            "'CANCELLED_BEFORE_ENTRY', 'NO_TRADE')",
            name="state",
        ),
        CheckConstraint("jsonb_typeof(metadata) = 'object'", name="metadata_object"),
        Index("ix_simulated_trade_events_trade_timestamp", "simulated_trade_id", "event_timestamp"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    simulated_trade_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("simulated_trades.id", ondelete="RESTRICT"), nullable=False
    )
    state: Mapped[str] = mapped_column(Text, nullable=False)
    event_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    price: Mapped[float | None] = mapped_column(Numeric(asdecimal=False))
    quantity: Mapped[float | None] = mapped_column(Numeric(asdecimal=False))
    realized_pnl: Mapped[float | None] = mapped_column(Numeric(asdecimal=False))
    costs: Mapped[float | None] = mapped_column(Numeric(asdecimal=False))
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PaperPosition(Base):
    __tablename__ = "paper_positions"
    __table_args__ = (
        CheckConstraint("side IN ('LONG', 'SHORT')", name="side"),
        CheckConstraint("quantity >= 0", name="quantity_nonnegative"),
        Index("ix_paper_positions_trade_observed_at", "simulated_trade_id", "observed_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    simulated_trade_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("simulated_trades.id", ondelete="RESTRICT"), nullable=False
    )
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    side: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[float] = mapped_column(Numeric(asdecimal=False), nullable=False)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    entry_price: Mapped[float | None] = mapped_column(Numeric(asdecimal=False))
    current_price: Mapped[float | None] = mapped_column(Numeric(asdecimal=False))
    unrealized_pnl: Mapped[float] = mapped_column(
        Numeric(asdecimal=False), nullable=False, server_default=text("0")
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    exit_price: Mapped[float | None] = mapped_column(Numeric(asdecimal=False))
    realized_pnl: Mapped[float] = mapped_column(
        Numeric(asdecimal=False), nullable=False, server_default=text("0")
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshots"
    __table_args__ = (
        UniqueConstraint("snapshot_timestamp", name="uq_portfolio_snapshots_timestamp"),
        Index("ix_portfolio_snapshots_timestamp_desc", text("snapshot_timestamp DESC")),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    snapshot_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cash: Mapped[float] = mapped_column(Numeric(asdecimal=False), nullable=False)
    gross_exposure: Mapped[float] = mapped_column(Numeric(asdecimal=False), nullable=False)
    net_exposure: Mapped[float] = mapped_column(Numeric(asdecimal=False), nullable=False)
    equity: Mapped[float] = mapped_column(Numeric(asdecimal=False), nullable=False)
    realized_pnl: Mapped[float] = mapped_column(Numeric(asdecimal=False), nullable=False)
    unrealized_pnl: Mapped[float] = mapped_column(Numeric(asdecimal=False), nullable=False)
    config_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
