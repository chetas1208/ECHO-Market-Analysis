"""Day 3 world-event tables (migration 0005).

Mirrors the migration's names and expressions exactly so ``alembic check`` reports no drift.
``event_revisions`` is append-only (Postgres triggers reject UPDATE/DELETE/TRUNCATE). All
scores stored elsewhere are heuristic values in [0, 1], not probabilities.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

CANONICAL_EVENT_FK = "canonical_events.id"


class EventSource(Base):
    """One piece of evidence for a canonical event. Idempotent via (event_id, content_hash)."""

    __tablename__ = "event_sources"
    __table_args__ = (
        CheckConstraint("length(btrim(provider)) > 0", name="provider_nonempty"),
        CheckConstraint("length(btrim(content_hash)) > 0", name="content_hash_nonempty"),
        CheckConstraint(
            "reliability IS NULL OR reliability BETWEEN 0 AND 1", name="reliability_unit"
        ),
        CheckConstraint("jsonb_typeof(metadata) = 'object'", name="metadata_object"),
        UniqueConstraint("event_id", "content_hash", name="uq_event_sources_event_id_content_hash"),
        Index("ix_event_sources_event_id", "event_id"),
        Index("ix_event_sources_provider_source_identifier", "provider", "source_identifier"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(
        Text, ForeignKey(CANONICAL_EVENT_FK, ondelete="RESTRICT"), nullable=False
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    source_name: Mapped[str] = mapped_column(Text, nullable=False)
    source_group: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    source_identifier: Mapped[str | None] = mapped_column(Text)
    headline: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_independent: Mapped[bool] = mapped_column(Boolean, nullable=False)
    syndicated_from: Mapped[str | None] = mapped_column(Text)
    reliability: Mapped[float | None] = mapped_column(Numeric(asdecimal=False))
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class EventFingerprint(Base):
    """Dedup index: one row per event."""

    __tablename__ = "event_fingerprints"
    __table_args__ = (
        CheckConstraint("jsonb_typeof(entity_keys) = 'array'", name="entity_keys_array"),
        CheckConstraint("jsonb_typeof(tokens) = 'array'", name="tokens_array"),
        Index("ix_event_fingerprints_fingerprint", "fingerprint"),
        Index("ix_event_fingerprints_occurred_at_desc", text("occurred_at DESC")),
    )

    event_id: Mapped[str] = mapped_column(
        Text, ForeignKey(CANONICAL_EVENT_FK, ondelete="RESTRICT"), primary_key=True
    )
    fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    event_class: Mapped[str] = mapped_column(Text, nullable=False)
    location_key: Mapped[str] = mapped_column(Text, nullable=False)
    time_bucket: Mapped[int] = mapped_column(BigInteger, nullable=False)
    entity_keys: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    tokens: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EventRevision(Base):
    """Append-only snapshot of an event's prior state (triggers reject UPDATE/DELETE/TRUNCATE)."""

    __tablename__ = "event_revisions"
    __table_args__ = (
        CheckConstraint("revision >= 1", name="revision_positive"),
        CheckConstraint("jsonb_typeof(snapshot) = 'object'", name="snapshot_object"),
        UniqueConstraint("event_id", "revision", name="uq_event_revisions_event_id_revision"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(
        Text, ForeignKey(CANONICAL_EVENT_FK, ondelete="RESTRICT"), nullable=False
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class EventRelationship(Base):
    """Link between two events. Table + repository stub only; no attribution logic yet."""

    __tablename__ = "event_relationships"
    __table_args__ = (
        CheckConstraint(
            "relationship_type IN ('RELATED', 'POSSIBLE_CAUSE', 'REACTION_TO')",
            name="relationship_type",
        ),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="confidence_unit"),
        CheckConstraint("source_event_id <> target_event_id", name="no_self_reference"),
        UniqueConstraint(
            "source_event_id",
            "target_event_id",
            "relationship_type",
            name="uq_event_relationships_pair_type",
        ),
        Index("ix_event_relationships_target_event_id", "target_event_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_event_id: Mapped[str] = mapped_column(
        Text, ForeignKey(CANONICAL_EVENT_FK, ondelete="RESTRICT"), nullable=False
    )
    target_event_id: Mapped[str] = mapped_column(
        Text, ForeignKey(CANONICAL_EVENT_FK, ondelete="RESTRICT"), nullable=False
    )
    relationship_type: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Numeric(asdecimal=False), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class WorldIngestError(Base):
    """Dead-letter row for a rejected provider payload (excerpt capped at 500 chars)."""

    __tablename__ = "world_ingest_errors"
    __table_args__ = (
        CheckConstraint(
            "payload_excerpt IS NULL OR char_length(payload_excerpt) <= 500",
            name="payload_excerpt_max",
        ),
        Index("ix_world_ingest_errors_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    error: Mapped[str] = mapped_column(Text, nullable=False)
    payload_hash: Mapped[str | None] = mapped_column(Text)
    payload_excerpt: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
