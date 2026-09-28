"""Persistent ShockGraph nodes, directed economic edges, and immutable snapshots."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

GRAPH_NODE_TYPES = (
    "("
    + ",".join(
        repr(value)
        for value in (
            "company",
            "commodity",
            "geography",
            "technology",
            "sector",
            "infrastructure",
            "channel",
        )
    )
    + ")"
)
GRAPH_RELATIONSHIPS = (
    "("
    + ",".join(
        repr(value)
        for value in (
            "SUPPLIER_OF",
            "CUSTOMER_OF",
            "COMPETITOR_OF",
            "SUBSTITUTE_FOR",
            "COMPLEMENT_TO",
            "EXPOSED_TO_COMMODITY",
            "OPERATES_IN_GEOGRAPHY",
            "GEOGRAPHIC_EXPOSURE",
            "REGULATORY_EXPOSURE",
            "TECHNOLOGY_DEPENDENCY",
            "RISK_SIMILARITY",
            "MEMBER_OF_SECTOR",
            "DEPENDS_ON_INFRASTRUCTURE",
            "DEPENDS_ON_ROUTE",
            "PRODUCES_COMMODITY",
            "CONSUMES_COMMODITY",
            "CHANNEL_EXPOSURE",
        )
    )
    + ")"
)


class GraphNode(Base):
    __tablename__ = "graph_nodes"
    __table_args__ = (
        CheckConstraint(f"node_type IN {GRAPH_NODE_TYPES}", name="node_type"),
        CheckConstraint("length(btrim(canonical_name)) > 0", name="canonical_name_nonempty"),
        CheckConstraint("jsonb_typeof(external_ids) = 'object'", name="external_ids_object"),
        CheckConstraint("jsonb_typeof(metadata) = 'object'", name="metadata_object"),
        UniqueConstraint("node_type", "canonical_name", name="uq_graph_nodes_type_name"),
        Index("ix_graph_nodes_node_type", "node_type"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    node_type: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_name: Mapped[str] = mapped_column(Text, nullable=False)
    symbol: Mapped[str | None] = mapped_column(Text)
    external_ids: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class GraphEdge(Base):
    __tablename__ = "graph_edges"
    __table_args__ = (
        CheckConstraint(f"relationship_type IN {GRAPH_RELATIONSHIPS}", name="relationship_type"),
        CheckConstraint("sign IN (-1, 1)", name="sign_unit"),
        CheckConstraint("weight BETWEEN 0 AND 1", name="weight_unit"),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="confidence_unit"),
        CheckConstraint("jsonb_typeof(provenance) = 'object'", name="provenance_object"),
        UniqueConstraint(
            "source_node_id", "target_node_id", "relationship_type", name="uq_graph_edges_pair_type"
        ),
        Index("ix_graph_edges_source_node_id", "source_node_id"),
        Index("ix_graph_edges_target_node_id", "target_node_id"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    source_node_id: Mapped[str] = mapped_column(
        Text, ForeignKey("graph_nodes.id", ondelete="RESTRICT"), nullable=False
    )
    target_node_id: Mapped[str] = mapped_column(
        Text, ForeignKey("graph_nodes.id", ondelete="RESTRICT"), nullable=False
    )
    relationship_type: Mapped[str] = mapped_column(Text, nullable=False)
    sign: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    weight: Mapped[float] = mapped_column(Numeric(asdecimal=False), nullable=False)
    confidence: Mapped[float] = mapped_column(Numeric(asdecimal=False), nullable=False)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class GraphSnapshot(Base):
    __tablename__ = "graph_snapshots"
    __table_args__ = (
        CheckConstraint("node_count >= 0", name="node_count_nonneg"),
        CheckConstraint("edge_count >= 0", name="edge_count_nonneg"),
        CheckConstraint("jsonb_typeof(metadata) = 'object'", name="metadata_object"),
        UniqueConstraint("content_hash", name="uq_graph_snapshots_content_hash"),
        Index("ix_graph_snapshots_created_at_desc", text("created_at DESC")),
    )

    snapshot_id: Mapped[str] = mapped_column(Text, primary_key=True)
    graph_version: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    node_count: Mapped[int] = mapped_column(Integer, nullable=False)
    edge_count: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )


class GraphSnapshotNode(Base):
    __tablename__ = "graph_snapshot_nodes"
    __table_args__ = (Index("ix_graph_snapshot_nodes_node_id", "node_id"),)

    snapshot_id: Mapped[str] = mapped_column(
        Text, ForeignKey("graph_snapshots.snapshot_id", ondelete="RESTRICT"), primary_key=True
    )
    node_id: Mapped[str] = mapped_column(Text, primary_key=True)
    node_type: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_name: Mapped[str] = mapped_column(Text, nullable=False)
    symbol: Mapped[str | None] = mapped_column(Text)
    external_ids: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False)


class GraphSnapshotEdge(Base):
    __tablename__ = "graph_snapshot_edges"
    __table_args__ = (Index("ix_graph_snapshot_edges_source_node_id", "source_node_id"),)

    snapshot_id: Mapped[str] = mapped_column(
        Text, ForeignKey("graph_snapshots.snapshot_id", ondelete="RESTRICT"), primary_key=True
    )
    edge_id: Mapped[str] = mapped_column(Text, primary_key=True)
    source_node_id: Mapped[str] = mapped_column(Text, nullable=False)
    target_node_id: Mapped[str] = mapped_column(Text, nullable=False)
    relationship_type: Mapped[str] = mapped_column(Text, nullable=False)
    sign: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    weight: Mapped[float] = mapped_column(Numeric(asdecimal=False), nullable=False)
    confidence: Mapped[float] = mapped_column(Numeric(asdecimal=False), nullable=False)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
