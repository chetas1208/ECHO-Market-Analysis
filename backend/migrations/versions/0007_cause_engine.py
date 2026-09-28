"""Immutable Cause Engine investigations and cluster observations.

Revision ID: 0007
Revises: 0006
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_IMMUTABLE_TABLES = ("cause_investigations", "cause_candidates", "cluster_shocks")


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE cause_investigations (
            investigation_id text PRIMARY KEY,
            market_shock_event_id text NOT NULL
                REFERENCES canonical_events(id) ON DELETE RESTRICT,
            graph_snapshot_id text NOT NULL
                REFERENCES graph_snapshots(snapshot_id) ON DELETE RESTRICT,
            created_at timestamptz NOT NULL DEFAULT now(),
            data_cutoff_at timestamptz NOT NULL,
            mode text NOT NULL,
            status text NOT NULL,
            engine_version text NOT NULL,
            config_version text NOT NULL,
            config_hash text NOT NULL,
            candidate_count integer NOT NULL,
            metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
            CONSTRAINT ck_cause_investigations_mode
                CHECK (mode IN ('REALTIME', 'RETROSPECTIVE')),
            CONSTRAINT ck_cause_investigations_status
                CHECK (status IN ('IDENTIFIED', 'AMBIGUOUS', 'UNKNOWN')),
            CONSTRAINT ck_cause_investigations_candidate_count_nonneg
                CHECK (candidate_count >= 0),
            CONSTRAINT ck_cause_investigations_metadata_object
                CHECK (jsonb_typeof(metadata) = 'object')
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_cause_investigations_market_shock_event_id "
        "ON cause_investigations (market_shock_event_id)"
    )
    op.execute(
        "CREATE INDEX ix_cause_investigations_data_cutoff_at "
        "ON cause_investigations (data_cutoff_at)"
    )
    op.execute(
        "CREATE INDEX ix_cause_investigations_created_at_desc "
        "ON cause_investigations (created_at DESC)"
    )

    op.execute(
        """
        CREATE TABLE cause_candidates (
            id bigserial PRIMARY KEY,
            investigation_id text NOT NULL
                REFERENCES cause_investigations(investigation_id) ON DELETE RESTRICT,
            candidate_event_id text NOT NULL
                REFERENCES canonical_events(id) ON DELETE RESTRICT,
            rank integer NOT NULL,
            cause_score numeric NOT NULL,
            temporal_score numeric NOT NULL,
            entity_score numeric NOT NULL,
            economic_score numeric NOT NULL,
            graph_score numeric NOT NULL,
            market_score numeric NOT NULL,
            source_score numeric NOT NULL,
            directional_consistency numeric NOT NULL,
            evidence jsonb NOT NULL DEFAULT '[]'::jsonb,
            graph_paths jsonb NOT NULL DEFAULT '[]'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_cause_candidates_rank_positive CHECK (rank >= 1),
            CONSTRAINT ck_cause_candidates_cause_score_unit CHECK (cause_score BETWEEN 0 AND 1),
            CONSTRAINT ck_cause_candidates_temporal_score_unit CHECK
                (temporal_score BETWEEN 0 AND 1),
            CONSTRAINT ck_cause_candidates_entity_score_unit CHECK (entity_score BETWEEN 0 AND 1),
            CONSTRAINT ck_cause_candidates_economic_score_unit CHECK
                (economic_score BETWEEN 0 AND 1),
            CONSTRAINT ck_cause_candidates_graph_score_unit CHECK (graph_score BETWEEN 0 AND 1),
            CONSTRAINT ck_cause_candidates_market_score_unit CHECK (market_score BETWEEN 0 AND 1),
            CONSTRAINT ck_cause_candidates_source_score_unit CHECK (source_score BETWEEN 0 AND 1),
            CONSTRAINT ck_cause_candidates_directional_consistency_unit CHECK
                (directional_consistency BETWEEN -1 AND 1),
            CONSTRAINT ck_cause_candidates_evidence_array CHECK (jsonb_typeof(evidence) = 'array'),
            CONSTRAINT ck_cause_candidates_graph_paths_array
                CHECK (jsonb_typeof(graph_paths) = 'array'),
            CONSTRAINT uq_cause_candidates_investigation_event
                UNIQUE (investigation_id, candidate_event_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_cause_candidates_investigation_id ON cause_candidates (investigation_id)"
    )
    op.execute(
        "CREATE INDEX ix_cause_candidates_candidate_event_id "
        "ON cause_candidates (candidate_event_id)"
    )

    op.execute(
        """
        CREATE TABLE cluster_shocks (
            cluster_id text PRIMARY KEY,
            cluster_key text NOT NULL,
            as_of timestamptz NOT NULL,
            direction text NOT NULL,
            members jsonb NOT NULL,
            member_count integer NOT NULL,
            abnormal_count integer NOT NULL,
            strength numeric NOT NULL,
            synchronization numeric NOT NULL,
            volume_confirmation numeric NOT NULL,
            graph_connectivity numeric NOT NULL,
            source_event_id text REFERENCES canonical_events(id) ON DELETE RESTRICT,
            metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_cluster_shocks_direction CHECK (direction IN ('POSITIVE', 'NEGATIVE')),
            CONSTRAINT ck_cluster_shocks_member_count_nonneg CHECK (member_count >= 0),
            CONSTRAINT ck_cluster_shocks_abnormal_count_nonneg CHECK (abnormal_count >= 0),
            CONSTRAINT ck_cluster_shocks_strength_unit CHECK (strength BETWEEN 0 AND 1),
            CONSTRAINT ck_cluster_shocks_synchronization_unit
                CHECK (synchronization BETWEEN 0 AND 1),
            CONSTRAINT ck_cluster_shocks_volume_confirmation_unit
                CHECK (volume_confirmation BETWEEN 0 AND 1),
            CONSTRAINT ck_cluster_shocks_graph_connectivity_unit
                CHECK (graph_connectivity BETWEEN 0 AND 1),
            CONSTRAINT ck_cluster_shocks_members_array CHECK (jsonb_typeof(members) = 'array'),
            CONSTRAINT ck_cluster_shocks_metadata_object CHECK (jsonb_typeof(metadata) = 'object')
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_cluster_shocks_cluster_key_as_of ON cluster_shocks (cluster_key, as_of)"
    )
    op.execute("CREATE INDEX ix_cluster_shocks_created_at_desc ON cluster_shocks (created_at DESC)")

    for table in _IMMUTABLE_TABLES:
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
    for table in reversed(_IMMUTABLE_TABLES):
        op.drop_table(table)
