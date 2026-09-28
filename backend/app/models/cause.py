"""Immutable Cause Engine investigations and explainable cluster observations."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
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


class CauseInvestigation(Base):
    """One immutable market-shock investigation at a declared information cutoff."""

    __tablename__ = "cause_investigations"
    __table_args__ = (
        CheckConstraint(
            "mode IN ('REALTIME', 'RETROSPECTIVE')",
            name="mode",
        ),
        CheckConstraint(
            "status IN ('IDENTIFIED', 'AMBIGUOUS', 'UNKNOWN')",
            name="status",
        ),
        CheckConstraint("candidate_count >= 0", name="candidate_count_nonneg"),
        CheckConstraint("jsonb_typeof(metadata) = 'object'", name="metadata_object"),
        Index("ix_cause_investigations_market_shock_event_id", "market_shock_event_id"),
        Index("ix_cause_investigations_data_cutoff_at", "data_cutoff_at"),
        Index("ix_cause_investigations_created_at_desc", text("created_at DESC")),
    )

    investigation_id: Mapped[str] = mapped_column(Text, primary_key=True)
    market_shock_event_id: Mapped[str] = mapped_column(
        Text, ForeignKey("canonical_events.id", ondelete="RESTRICT"), nullable=False
    )
    graph_snapshot_id: Mapped[str] = mapped_column(
        Text, ForeignKey("graph_snapshots.snapshot_id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    data_cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    mode: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    engine_version: Mapped[str] = mapped_column(Text, nullable=False)
    config_version: Mapped[str] = mapped_column(Text, nullable=False)
    config_hash: Mapped[str] = mapped_column(Text, nullable=False)
    candidate_count: Mapped[int] = mapped_column(Integer, nullable=False)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )


class CauseCandidate(Base):
    """One scored candidate cause belonging to an immutable investigation."""

    __tablename__ = "cause_candidates"
    __table_args__ = (
        CheckConstraint("rank >= 1", name="rank_positive"),
        CheckConstraint("cause_score BETWEEN 0 AND 1", name="cause_score_unit"),
        CheckConstraint("temporal_score BETWEEN 0 AND 1", name="temporal_score_unit"),
        CheckConstraint("entity_score BETWEEN 0 AND 1", name="entity_score_unit"),
        CheckConstraint("economic_score BETWEEN 0 AND 1", name="economic_score_unit"),
        CheckConstraint("graph_score BETWEEN 0 AND 1", name="graph_score_unit"),
        CheckConstraint("market_score BETWEEN 0 AND 1", name="market_score_unit"),
        CheckConstraint("source_score BETWEEN 0 AND 1", name="source_score_unit"),
        CheckConstraint(
            "directional_consistency BETWEEN -1 AND 1", name="directional_consistency_unit"
        ),
        CheckConstraint("jsonb_typeof(evidence) = 'array'", name="evidence_array"),
        CheckConstraint("jsonb_typeof(graph_paths) = 'array'", name="graph_paths_array"),
        Index("ix_cause_candidates_investigation_id", "investigation_id"),
        Index("ix_cause_candidates_candidate_event_id", "candidate_event_id"),
        UniqueConstraint(
            "investigation_id",
            "candidate_event_id",
            name="uq_cause_candidates_investigation_event",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    investigation_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("cause_investigations.investigation_id", ondelete="RESTRICT"),
        nullable=False,
    )
    candidate_event_id: Mapped[str] = mapped_column(
        Text, ForeignKey("canonical_events.id", ondelete="RESTRICT"), nullable=False
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    cause_score: Mapped[float] = mapped_column(Numeric(asdecimal=False), nullable=False)
    temporal_score: Mapped[float] = mapped_column(Numeric(asdecimal=False), nullable=False)
    entity_score: Mapped[float] = mapped_column(Numeric(asdecimal=False), nullable=False)
    economic_score: Mapped[float] = mapped_column(Numeric(asdecimal=False), nullable=False)
    graph_score: Mapped[float] = mapped_column(Numeric(asdecimal=False), nullable=False)
    market_score: Mapped[float] = mapped_column(Numeric(asdecimal=False), nullable=False)
    source_score: Mapped[float] = mapped_column(Numeric(asdecimal=False), nullable=False)
    directional_consistency: Mapped[float] = mapped_column(Numeric(asdecimal=False), nullable=False)
    evidence: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    graph_paths: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ClusterShock(Base):
    """Immutable structured observation of a synchronized related-stock move."""

    __tablename__ = "cluster_shocks"
    __table_args__ = (
        CheckConstraint("direction IN ('POSITIVE', 'NEGATIVE')", name="direction"),
        CheckConstraint("member_count >= 0", name="member_count_nonneg"),
        CheckConstraint("abnormal_count >= 0", name="abnormal_count_nonneg"),
        CheckConstraint("strength BETWEEN 0 AND 1", name="strength_unit"),
        CheckConstraint("synchronization BETWEEN 0 AND 1", name="synchronization_unit"),
        CheckConstraint("volume_confirmation BETWEEN 0 AND 1", name="volume_confirmation_unit"),
        CheckConstraint("graph_connectivity BETWEEN 0 AND 1", name="graph_connectivity_unit"),
        CheckConstraint("jsonb_typeof(members) = 'array'", name="members_array"),
        CheckConstraint("jsonb_typeof(metadata) = 'object'", name="metadata_object"),
        Index("ix_cluster_shocks_cluster_key_as_of", "cluster_key", "as_of"),
        Index("ix_cluster_shocks_created_at_desc", text("created_at DESC")),
    )

    cluster_id: Mapped[str] = mapped_column(Text, primary_key=True)
    cluster_key: Mapped[str] = mapped_column(Text, nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    direction: Mapped[str] = mapped_column(Text, nullable=False)
    members: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    member_count: Mapped[int] = mapped_column(Integer, nullable=False)
    abnormal_count: Mapped[int] = mapped_column(Integer, nullable=False)
    strength: Mapped[float] = mapped_column(Numeric(asdecimal=False), nullable=False)
    synchronization: Mapped[float] = mapped_column(Numeric(asdecimal=False), nullable=False)
    volume_confirmation: Mapped[float] = mapped_column(Numeric(asdecimal=False), nullable=False)
    graph_connectivity: Mapped[float] = mapped_column(Numeric(asdecimal=False), nullable=False)
    source_event_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("canonical_events.id", ondelete="RESTRICT")
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
