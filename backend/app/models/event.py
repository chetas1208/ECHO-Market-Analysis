from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    Numeric,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CanonicalEvent(Base):
    """Normalized event consumed by all downstream services (Plan section 7)."""

    __tablename__ = "canonical_events"
    # Mirrors migration 0001 exactly (names and expressions); the ck_ prefix comes from the
    # metadata naming convention, so CHECK names here omit it.
    __table_args__ = (
        CheckConstraint("id ~ '^evt_[a-z0-9_]+$'", name="id_format"),
        CheckConstraint("source_type IN ('WORLD', 'MARKET', 'FINANCIAL')", name="source_type"),
        CheckConstraint("length(btrim(title)) > 0", name="title_nonempty"),
        CheckConstraint("jsonb_typeof(entities) = 'array'", name="entities_array"),
        CheckConstraint("jsonb_typeof(companies) = 'array'", name="companies_array"),
        CheckConstraint("jsonb_typeof(locations) = 'array'", name="locations_array"),
        CheckConstraint(
            "jsonb_typeof(economic_channels) = 'object'", name="economic_channels_object"
        ),
        CheckConstraint("jsonb_typeof(source_refs) = 'array'", name="source_refs_array"),
        CheckConstraint("jsonb_typeof(metadata) = 'object'", name="metadata_object"),
        CheckConstraint("severity BETWEEN 0 AND 1", name="severity_unit"),
        CheckConstraint("novelty BETWEEN 0 AND 1", name="novelty_unit"),
        CheckConstraint("corroboration BETWEEN 0 AND 1", name="corroboration_unit"),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="confidence_unit"),
        # Migration 0005 (Day 3 world events).
        CheckConstraint("revision >= 1", name="revision_positive"),
        CheckConstraint("source_count >= 0", name="source_count_nonneg"),
        CheckConstraint("independent_source_count >= 0", name="independent_source_count_nonneg"),
        Index("ix_canonical_events_timestamp", "timestamp"),
        Index("ix_canonical_events_source_type", "source_type"),
        Index("ix_canonical_events_event_type", "event_type"),
        Index("ix_canonical_events_severity", "severity"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Stored uppercase (WORLD | MARKET | FINANCIAL); the API represents it in lowercase.
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    entities: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    companies: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    locations: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    economic_channels: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    severity: Mapped[float] = mapped_column(Numeric(asdecimal=False), nullable=False)
    novelty: Mapped[float] = mapped_column(Numeric(asdecimal=False), nullable=False)
    corroboration: Mapped[float] = mapped_column(Numeric(asdecimal=False), nullable=False)
    confidence: Mapped[float] = mapped_column(Numeric(asdecimal=False), nullable=False)
    source_refs: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    is_mock: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # Migration 0005. ``revision``/``updated_at``/source counts are written ONLY through
    # WorldRepository.update_event_scores (the single mutation path for canonical_events).
    revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    independent_source_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )
