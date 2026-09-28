"""ShockGraph relational truth and immutable snapshots.

Revision ID: 0006
Revises: 0005
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TRIGGER_TABLES = (
    "graph_snapshots",
    "graph_snapshot_nodes",
    "graph_snapshot_edges",
)
_NODE_TYPES_SQL = (
    "'company','commodity','geography','technology','sector','infrastructure','channel'"
)
_RELATIONSHIPS_SQL = (
    "'SUPPLIER_OF','CUSTOMER_OF','COMPETITOR_OF','SUBSTITUTE_FOR','COMPLEMENT_TO',"
    "'EXPOSED_TO_COMMODITY','OPERATES_IN_GEOGRAPHY','GEOGRAPHIC_EXPOSURE',"
    "'REGULATORY_EXPOSURE','TECHNOLOGY_DEPENDENCY','RISK_SIMILARITY','MEMBER_OF_SECTOR',"
    "'DEPENDS_ON_INFRASTRUCTURE','DEPENDS_ON_ROUTE','PRODUCES_COMMODITY',"
    "'CONSUMES_COMMODITY','CHANNEL_EXPOSURE'"
)


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE graph_nodes (
            id text PRIMARY KEY,
            node_type text NOT NULL,
            canonical_name text NOT NULL,
            symbol text,
            external_ids jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            metadata jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_graph_nodes_node_type CHECK (node_type IN ({_NODE_TYPES_SQL})),
            CONSTRAINT ck_graph_nodes_canonical_name_nonempty CHECK
                (length(btrim(canonical_name)) > 0),
            CONSTRAINT ck_graph_nodes_external_ids_object CHECK
                (jsonb_typeof(external_ids) = 'object'),
            CONSTRAINT ck_graph_nodes_metadata_object CHECK (jsonb_typeof(metadata) = 'object'),
            CONSTRAINT uq_graph_nodes_type_name UNIQUE (node_type, canonical_name)
        )
        """
    )
    op.execute("CREATE INDEX ix_graph_nodes_node_type ON graph_nodes (node_type)")
    op.execute(
        f"""
        CREATE TABLE graph_edges (
            id text PRIMARY KEY,
            source_node_id text NOT NULL REFERENCES graph_nodes(id) ON DELETE RESTRICT,
            target_node_id text NOT NULL REFERENCES graph_nodes(id) ON DELETE RESTRICT,
            relationship_type text NOT NULL,
            sign smallint NOT NULL,
            weight numeric NOT NULL,
            confidence numeric NOT NULL,
            provenance jsonb NOT NULL,
            valid_from timestamptz NOT NULL DEFAULT now(),
            valid_to timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_graph_edges_relationship_type CHECK
                (relationship_type IN ({_RELATIONSHIPS_SQL})),
            CONSTRAINT ck_graph_edges_sign_unit CHECK (sign IN (-1, 1)),
            CONSTRAINT ck_graph_edges_weight_unit CHECK (weight BETWEEN 0 AND 1),
            CONSTRAINT ck_graph_edges_confidence_unit CHECK (confidence BETWEEN 0 AND 1),
            CONSTRAINT ck_graph_edges_provenance_object CHECK (jsonb_typeof(provenance) = 'object'),
            CONSTRAINT uq_graph_edges_pair_type UNIQUE
                (source_node_id, target_node_id, relationship_type)
        )
        """
    )
    op.execute("CREATE INDEX ix_graph_edges_source_node_id ON graph_edges (source_node_id)")
    op.execute("CREATE INDEX ix_graph_edges_target_node_id ON graph_edges (target_node_id)")
    op.execute(
        """
        CREATE TABLE graph_snapshots (
            snapshot_id text PRIMARY KEY,
            graph_version text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            node_count integer NOT NULL,
            edge_count integer NOT NULL,
            content_hash text NOT NULL,
            metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
            CONSTRAINT ck_graph_snapshots_node_count_nonneg CHECK (node_count >= 0),
            CONSTRAINT ck_graph_snapshots_edge_count_nonneg CHECK (edge_count >= 0),
            CONSTRAINT ck_graph_snapshots_metadata_object CHECK (jsonb_typeof(metadata) = 'object'),
            CONSTRAINT uq_graph_snapshots_content_hash UNIQUE (content_hash)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_graph_snapshots_created_at_desc ON graph_snapshots (created_at DESC)"
    )
    op.execute(
        """
        CREATE TABLE graph_snapshot_nodes (
            snapshot_id text NOT NULL REFERENCES graph_snapshots(snapshot_id) ON DELETE RESTRICT,
            node_id text NOT NULL,
            node_type text NOT NULL,
            canonical_name text NOT NULL,
            symbol text,
            external_ids jsonb NOT NULL,
            metadata jsonb NOT NULL,
            PRIMARY KEY (snapshot_id, node_id)
        )
        """
    )
    op.execute("CREATE INDEX ix_graph_snapshot_nodes_node_id ON graph_snapshot_nodes (node_id)")
    op.execute(
        """
        CREATE TABLE graph_snapshot_edges (
            snapshot_id text NOT NULL REFERENCES graph_snapshots(snapshot_id) ON DELETE RESTRICT,
            edge_id text NOT NULL,
            source_node_id text NOT NULL,
            target_node_id text NOT NULL,
            relationship_type text NOT NULL,
            sign smallint NOT NULL,
            weight numeric NOT NULL,
            confidence numeric NOT NULL,
            provenance jsonb NOT NULL,
            valid_from timestamptz NOT NULL,
            valid_to timestamptz,
            PRIMARY KEY (snapshot_id, edge_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_graph_snapshot_edges_source_node_id "
        "ON graph_snapshot_edges (source_node_id)"
    )
    for table in _TRIGGER_TABLES:
        row_trigger = f"trg_{table}_immutable_row"
        truncate_trigger = f"trg_{table}_immutable_truncate"
        op.execute(
            f"CREATE TRIGGER {row_trigger} BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION echo_forbid_ledger_mutation()"
        )
        op.execute(
            f"CREATE TRIGGER {truncate_trigger} BEFORE TRUNCATE ON {table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION echo_forbid_ledger_mutation()"
        )
        op.execute(f"ALTER TABLE {table} ENABLE ALWAYS TRIGGER {row_trigger}")
        op.execute(f"ALTER TABLE {table} ENABLE ALWAYS TRIGGER {truncate_trigger}")


def downgrade() -> None:
    for table in reversed(_TRIGGER_TABLES):
        op.drop_table(table)
    op.drop_index("ix_graph_edges_target_node_id", table_name="graph_edges")
    op.drop_index("ix_graph_edges_source_node_id", table_name="graph_edges")
    op.drop_table("graph_edges")
    op.drop_index("ix_graph_nodes_node_type", table_name="graph_nodes")
    op.drop_table("graph_nodes")
