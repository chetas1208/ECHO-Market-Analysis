"""Append-only paper execution audit trail."""

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


class OrderIntentRecord(Base):
    __tablename__ = "order_intents"
    __table_args__ = (
        CheckConstraint("side IN ('LONG', 'SHORT')", name="side"),
        CheckConstraint("execution_source IN ('REPLAY', 'PAPER')", name="execution_source"),
        CheckConstraint(
            "state IN ('CREATED', 'SUBMITTING', 'SUBMITTED', 'PARTIALLY_FILLED', "
            "'FILLED', 'CANCELLED', 'REJECTED', 'EXPIRED', 'FAILED', "
            "'REJECTED_PRE_EXECUTION')",
            name="state",
        ),
        CheckConstraint("jsonb_typeof(stop_metadata) = 'object'", name="stop_metadata_object"),
        CheckConstraint("jsonb_typeof(hedge_metadata) = 'object'", name="hedge_metadata_object"),
        UniqueConstraint("idempotency_key", name="uq_order_intents_idempotency_key"),
        Index("ix_order_intents_decision_id", "decision_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    decision_id: Mapped[str] = mapped_column(Text, nullable=False)
    forecast_id: Mapped[str] = mapped_column(Text, nullable=False)
    strategy_version: Mapped[str] = mapped_column(Text, nullable=False)
    config_hash: Mapped[str] = mapped_column(Text, nullable=False)
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    side: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[float | None] = mapped_column(Numeric(asdecimal=False))
    notional: Mapped[float | None] = mapped_column(Numeric(asdecimal=False))
    order_type: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'MARKET'"))
    time_in_force: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'DAY'"))
    limit_price: Mapped[float | None] = mapped_column(Numeric(asdecimal=False))
    stop_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    hedge_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    execution_source: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    external_order_id: Mapped[str | None] = mapped_column(Text)
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)


class ExecutionFillRecord(Base):
    __tablename__ = "execution_fills"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("price > 0", name="price_positive"),
        UniqueConstraint("external_fill_id", name="uq_execution_fills_external_fill_id"),
        Index("ix_execution_fills_order_intent", "order_intent_id", "timestamp"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_intent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("order_intents.id", ondelete="RESTRICT"), nullable=False
    )
    external_order_id: Mapped[str] = mapped_column(Text, nullable=False)
    external_fill_id: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    quantity: Mapped[float] = mapped_column(Numeric(asdecimal=False), nullable=False)
    price: Mapped[float] = mapped_column(Numeric(asdecimal=False), nullable=False)
    fees: Mapped[float] = mapped_column(
        Numeric(asdecimal=False), nullable=False, server_default=text("0")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ExecutionEventRecord(Base):
    __tablename__ = "execution_events"
    __table_args__ = (
        CheckConstraint("jsonb_typeof(metadata) = 'object'", name="metadata_object"),
        Index("ix_execution_events_intent_timestamp", "order_intent_id", "event_timestamp"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_intent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("order_intents.id", ondelete="RESTRICT"), nullable=False
    )
    state: Mapped[str] = mapped_column(Text, nullable=False)
    event_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class BrokerReconciliationRecord(Base):
    __tablename__ = "broker_reconciliations"
    __table_args__ = (
        CheckConstraint("jsonb_typeof(discrepancies) = 'array'", name="discrepancies_array"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    discrepancies: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    account_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
