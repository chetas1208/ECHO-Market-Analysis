"""forecast ledger (immutable): forecast_runs, forecast_points

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-20

The ledger is append-only (decision D-005). Enforcement lives in the database:
BEFORE UPDATE/DELETE row triggers and a BEFORE TRUNCATE statement trigger raise on
both tables. Foreign keys are ON DELETE RESTRICT so no cascade path can delete ledger
rows. New information creates a new forecast vintage (a new forecast_runs row).

forecast_points quantiles are CUMULATIVE ABNORMAL RETURNS over the horizon (decision
D-003), not prices.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE forecast_runs (
            id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            event_id             text REFERENCES canonical_events (id) ON DELETE RESTRICT,
            symbol               text NOT NULL,
            created_at           timestamptz NOT NULL DEFAULT now(),
            prediction_timestamp timestamptz NOT NULL,
            data_cutoff_at       timestamptz NOT NULL,
            model_version        text NOT NULL,
            feature_version      text NOT NULL,
            graph_snapshot_id    text,
            event_snapshot_id    text,
            feature_hash         text,
            metadata             jsonb NOT NULL DEFAULT '{}'::jsonb,
            CONSTRAINT ck_forecast_runs_symbol_nonempty CHECK (length(btrim(symbol)) > 0),
            CONSTRAINT ck_forecast_runs_cutoff_not_after_prediction
                CHECK (data_cutoff_at <= prediction_timestamp),
            CONSTRAINT ck_forecast_runs_metadata_object CHECK (jsonb_typeof(metadata) = 'object')
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_forecast_runs_symbol_prediction_timestamp "
        "ON forecast_runs (symbol, prediction_timestamp)"
    )
    op.execute("CREATE INDEX ix_forecast_runs_event_id ON forecast_runs (event_id)")

    op.execute(
        """
        CREATE TABLE forecast_points (
            id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            forecast_run_id      uuid NOT NULL
                                 REFERENCES forecast_runs (id) ON DELETE RESTRICT,
            horizon              text NOT NULL,
            horizon_trading_days integer NOT NULL,
            target_timestamp     timestamptz NOT NULL,
            -- Quantiles of cumulative ABNORMAL return over the horizon (not price).
            q10                  numeric NOT NULL,
            q50                  numeric NOT NULL,
            q90                  numeric NOT NULL,
            probability_positive numeric NOT NULL,
            created_at           timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_forecast_points_horizon
                CHECK (horizon IN ('1D', '2D', '5D', '10D', '20D')),
            CONSTRAINT ck_forecast_points_horizon_days_match CHECK (
                (horizon, horizon_trading_days)
                IN (('1D', 1), ('2D', 2), ('5D', 5), ('10D', 10), ('20D', 20))
            ),
            CONSTRAINT ck_forecast_points_quantile_order CHECK (q10 <= q50 AND q50 <= q90),
            CONSTRAINT ck_forecast_points_probability_positive_unit
                CHECK (probability_positive BETWEEN 0 AND 1),
            CONSTRAINT uq_forecast_points_forecast_run_id_horizon
                UNIQUE (forecast_run_id, horizon)
        )
        """
    )
    # UNIQUE (forecast_run_id, horizon) is backed by an index on exactly those columns,
    # which serves the (forecast_run_id, horizon) lookup path.

    op.execute(
        """
        CREATE FUNCTION echo_forbid_ledger_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION
                'table "%" is an immutable, append-only ledger: % is not allowed',
                TG_TABLE_NAME, TG_OP
                USING ERRCODE = 'restrict_violation';
        END;
        $$
        """
    )
    for table in ("forecast_runs", "forecast_points"):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_immutable_row
                BEFORE UPDATE OR DELETE ON {table}
                FOR EACH ROW EXECUTE FUNCTION echo_forbid_ledger_mutation()
            """
        )
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_immutable_truncate
                BEFORE TRUNCATE ON {table}
                FOR EACH STATEMENT EXECUTE FUNCTION echo_forbid_ledger_mutation()
            """
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS forecast_points")
    op.execute("DROP TABLE IF EXISTS forecast_runs")
    op.execute("DROP FUNCTION IF EXISTS echo_forbid_ledger_mutation()")
