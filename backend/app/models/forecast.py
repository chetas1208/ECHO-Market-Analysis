"""Immutable prediction ledger tables (decisions D-003/D-005, Plan section 14).

Rows are append-only; Postgres triggers reject UPDATE/DELETE/TRUNCATE (see migration 0002).
Point targets are cumulative ABNORMAL returns, not prices.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ForecastRun(Base):
    __tablename__ = "forecast_runs"
    # Mirrors migration 0002 (ck_ prefix is added by the metadata naming convention).
    __table_args__ = (
        CheckConstraint("length(btrim(symbol)) > 0", name="symbol_nonempty"),
        CheckConstraint(
            "data_cutoff_at <= prediction_timestamp", name="cutoff_not_after_prediction"
        ),
        CheckConstraint("jsonb_typeof(metadata) = 'object'", name="metadata_object"),
        Index("ix_forecast_runs_symbol_prediction_timestamp", "symbol", "prediction_timestamp"),
        Index("ix_forecast_runs_event_id", "event_id"),
        Index(
            "uq_forecast_runs_request_hash",
            "request_hash",
            unique=True,
            postgresql_where=text("request_hash IS NOT NULL"),
        ),
        Index(
            "uq_forecast_runs_idempotency_key",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
        Index(
            "uq_forecast_runs_content_hash",
            "content_hash",
            unique=True,
            postgresql_where=text("content_hash IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    event_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("canonical_events.id", ondelete="RESTRICT")
    )
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    prediction_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    data_cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    model_version: Mapped[str] = mapped_column(Text, nullable=False)
    feature_version: Mapped[str] = mapped_column(Text, nullable=False)
    graph_snapshot_id: Mapped[str | None] = mapped_column(Text)
    event_snapshot_id: Mapped[str | None] = mapped_column(Text)
    feature_hash: Mapped[str | None] = mapped_column(Text)
    model_artifact_hash: Mapped[str | None] = mapped_column(Text)
    config_hash: Mapped[str | None] = mapped_column(Text)
    forecasting_engine_version: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'echo-forecast-legacy'")
    )
    recommended_horizon: Mapped[str | None] = mapped_column(Text)
    information_half_life: Mapped[float | None] = mapped_column(Numeric(asdecimal=False))
    ood_status: Mapped[str | None] = mapped_column(Text)
    abstention_state: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str | None] = mapped_column(Text)
    request_hash: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str | None] = mapped_column(Text)
    event_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    feature_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )


class ForecastPoint(Base):
    __tablename__ = "forecast_points"
    # Mirrors migration 0002 (ck_ prefix is added by the metadata naming convention).
    __table_args__ = (
        CheckConstraint("horizon IN ('1D', '2D', '5D', '10D', '20D')", name="horizon"),
        CheckConstraint(
            "(horizon, horizon_trading_days) "
            "IN (('1D', 1), ('2D', 2), ('5D', 5), ('10D', 10), ('20D', 20))",
            name="horizon_days_match",
        ),
        CheckConstraint("q10 <= q50 AND q50 <= q90", name="quantile_order"),
        CheckConstraint("probability_positive BETWEEN 0 AND 1", name="probability_positive_unit"),
        UniqueConstraint(
            "forecast_run_id", "horizon", name="uq_forecast_points_forecast_run_id_horizon"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    forecast_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("forecast_runs.id", ondelete="RESTRICT"), nullable=False
    )
    horizon: Mapped[str] = mapped_column(Text, nullable=False)  # 1D | 2D | 5D | 10D | 20D
    horizon_trading_days: Mapped[int] = mapped_column(Integer, nullable=False)
    target_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Quantiles of cumulative abnormal return over the horizon (not price).
    q10: Mapped[float] = mapped_column(Numeric(asdecimal=False), nullable=False)
    q50: Mapped[float] = mapped_column(Numeric(asdecimal=False), nullable=False)
    q90: Mapped[float] = mapped_column(Numeric(asdecimal=False), nullable=False)
    probability_positive: Mapped[float] = mapped_column(Numeric(asdecimal=False), nullable=False)
    expected_abnormal_return: Mapped[float | None] = mapped_column(Numeric(asdecimal=False))
    forecast_risk: Mapped[float | None] = mapped_column(Numeric(asdecimal=False))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
