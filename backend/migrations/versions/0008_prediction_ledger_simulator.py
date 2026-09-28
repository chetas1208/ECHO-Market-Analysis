"""Day 7 immutable prediction vintages, actuals, evaluation, and simulation.

Revision ID: 0008
Revises: 0007

The existing forecast ledger is extended in place. Every new Day 7 table is
append-only at the database boundary; later observations and execution outcomes
are new rows, never rewrites of historical predictions or plans.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_IMMUTABLE_TABLES = (
    "forecast_actuals",
    "forecast_evaluations",
    "simulated_trades",
    "simulated_trade_events",
    "paper_positions",
    "portfolio_snapshots",
)


def _add_columns() -> None:
    op.execute(
        """
        ALTER TABLE forecast_runs
            ADD COLUMN IF NOT EXISTS model_artifact_hash text,
            ADD COLUMN IF NOT EXISTS config_hash text,
            ADD COLUMN IF NOT EXISTS forecasting_engine_version text
                NOT NULL DEFAULT 'echo-forecast-legacy',
            ADD COLUMN IF NOT EXISTS recommended_horizon text,
            ADD COLUMN IF NOT EXISTS information_half_life numeric,
            ADD COLUMN IF NOT EXISTS ood_status text,
            ADD COLUMN IF NOT EXISTS abstention_state text,
            ADD COLUMN IF NOT EXISTS content_hash text,
            ADD COLUMN IF NOT EXISTS request_hash text,
            ADD COLUMN IF NOT EXISTS idempotency_key text,
            ADD COLUMN IF NOT EXISTS event_snapshot jsonb,
            ADD COLUMN IF NOT EXISTS feature_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
            ADD CONSTRAINT ck_forecast_runs_recommended_horizon
                CHECK (recommended_horizon IS NULL OR recommended_horizon IN
                    ('1D', '2D', '5D', '10D', '20D')),
            ADD CONSTRAINT ck_forecast_runs_ood_status
                CHECK (ood_status IS NULL OR ood_status IN ('IN_DISTRIBUTION', 'OOD', 'UNKNOWN')),
            ADD CONSTRAINT ck_forecast_runs_abstention_state
                CHECK (abstention_state IS NULL OR abstention_state IN
                    ('NONE', 'FORECAST_UNAVAILABLE')),
            ADD CONSTRAINT ck_forecast_runs_event_snapshot_object
                CHECK (event_snapshot IS NULL OR jsonb_typeof(event_snapshot) = 'object'),
            ADD CONSTRAINT ck_forecast_runs_feature_snapshot_object
                CHECK (jsonb_typeof(feature_snapshot) = 'object')
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_forecast_runs_request_hash
            ON forecast_runs (request_hash)
            WHERE request_hash IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_forecast_runs_idempotency_key
            ON forecast_runs (idempotency_key)
            WHERE idempotency_key IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_forecast_runs_content_hash
            ON forecast_runs (content_hash)
            WHERE content_hash IS NOT NULL
        """
    )
    op.execute(
        """
        ALTER TABLE forecast_points
            ADD COLUMN IF NOT EXISTS expected_abnormal_return numeric,
            ADD COLUMN IF NOT EXISTS forecast_risk numeric,
            ADD CONSTRAINT ck_forecast_points_forecast_risk_nonnegative
                CHECK (forecast_risk IS NULL OR forecast_risk >= 0)
        """
    )


def _create_actuals() -> None:
    op.execute(
        """
        CREATE TABLE forecast_actuals (
            id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            forecast_run_id         uuid NOT NULL
                REFERENCES forecast_runs(id) ON DELETE RESTRICT,
            symbol                   text NOT NULL,
            horizon                  text NOT NULL,
            observed_at              timestamptz NOT NULL,
            market_timestamp         timestamptz NOT NULL,
            actual_price             numeric,
            actual_return            numeric,
            actual_abnormal_return   numeric,
            market_return            numeric,
            sector_return            numeric,
            source                   text NOT NULL,
            observation_hash         text NOT NULL,
            created_at               timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_forecast_actuals_symbol_nonempty CHECK (length(btrim(symbol)) > 0),
            CONSTRAINT ck_forecast_actuals_horizon CHECK
                (horizon IN ('INTRADAY', '1D', '2D', '5D', '10D', '20D')),
            CONSTRAINT ck_forecast_actuals_source_nonempty CHECK (length(btrim(source)) > 0),
            CONSTRAINT uq_forecast_actuals_run_horizon_timestamp
                UNIQUE (forecast_run_id, horizon, market_timestamp),
            CONSTRAINT uq_forecast_actuals_observation_hash UNIQUE (observation_hash)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_forecast_actuals_run_observed_at "
        "ON forecast_actuals (forecast_run_id, observed_at)"
    )
    op.execute(
        "CREATE INDEX ix_forecast_actuals_symbol_market_timestamp "
        "ON forecast_actuals (symbol, market_timestamp)"
    )


def _create_evaluations() -> None:
    op.execute(
        """
        CREATE TABLE forecast_evaluations (
            id                     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            forecast_run_id       uuid NOT NULL
                REFERENCES forecast_runs(id) ON DELETE RESTRICT,
            horizon                text NOT NULL,
            evaluated_at           timestamptz NOT NULL,
            status                  text NOT NULL,
            predicted_q10          numeric,
            predicted_q50          numeric,
            predicted_q90          numeric,
            probability_positive   numeric,
            actual_abnormal_return numeric,
            absolute_error         numeric,
            squared_error          numeric,
            directional_correct    boolean,
            interval_covered       boolean,
            pinball_q10            numeric,
            pinball_q50            numeric,
            pinball_q90            numeric,
            brier_contribution     numeric,
            evaluation_hash        text NOT NULL,
            created_at              timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_forecast_evaluations_horizon CHECK
                (horizon IN ('1D', '2D', '5D', '10D', '20D')),
            CONSTRAINT ck_forecast_evaluations_status CHECK
                (status IN ('PENDING', 'PARTIAL', 'COMPLETE', 'UNAVAILABLE')),
            CONSTRAINT ck_forecast_evaluations_probability_unit CHECK
                (probability_positive IS NULL OR probability_positive BETWEEN 0 AND 1),
            CONSTRAINT uq_forecast_evaluations_hash UNIQUE (evaluation_hash)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_forecast_evaluations_run_horizon "
        "ON forecast_evaluations (forecast_run_id, horizon)"
    )


def _create_simulator() -> None:
    op.execute(
        """
        CREATE TABLE simulated_trades (
            id                          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            forecast_run_id            uuid NOT NULL
                REFERENCES forecast_runs(id) ON DELETE RESTRICT,
            created_at                  timestamptz NOT NULL DEFAULT now(),
            symbol                      text NOT NULL,
            side                        text NOT NULL,
            decision_timestamp          timestamptz NOT NULL,
            entry_timestamp             timestamptz,
            entry_price                 numeric,
            planned_exit_horizon        text NOT NULL,
            planned_exit_timestamp      timestamptz NOT NULL,
            position_size               numeric NOT NULL DEFAULT 0,
            notional                    numeric NOT NULL DEFAULT 0,
            hedge_symbol                text,
            hedge_ratio                 numeric NOT NULL DEFAULT 0,
            stop_type                   text,
            stop_value                  numeric,
            take_profit                 numeric,
            strategy_version            text NOT NULL,
            config_hash                 text NOT NULL,
            status                      text NOT NULL,
            gross_pnl                   numeric NOT NULL DEFAULT 0,
            costs                       numeric NOT NULL DEFAULT 0,
            hedge_pnl                   numeric NOT NULL DEFAULT 0,
            net_pnl                     numeric NOT NULL DEFAULT 0,
            return_on_allocated_capital numeric,
            plan_hash                   text NOT NULL,
            metadata                    jsonb NOT NULL DEFAULT '{}'::jsonb,
            CONSTRAINT ck_simulated_trades_symbol_nonempty CHECK (length(btrim(symbol)) > 0),
            CONSTRAINT ck_simulated_trades_side CHECK (side IN ('LONG', 'SHORT', 'NO_TRADE')),
            CONSTRAINT ck_simulated_trades_horizon CHECK
                (planned_exit_horizon IN ('1D', '2D', '5D', '10D', '20D')),
            CONSTRAINT ck_simulated_trades_size_nonnegative CHECK (position_size >= 0),
            CONSTRAINT ck_simulated_trades_notional_nonnegative CHECK (notional >= 0),
            CONSTRAINT ck_simulated_trades_hedge_ratio_nonnegative CHECK (hedge_ratio >= 0),
            CONSTRAINT ck_simulated_trades_status CHECK
                (status IN ('PLANNED', 'OPEN', 'CLOSED', 'STOPPED', 'EXPIRED',
                            'CANCELLED_BEFORE_ENTRY', 'NO_TRADE')),
            CONSTRAINT ck_simulated_trades_metadata_object
                CHECK (jsonb_typeof(metadata) = 'object'),
            CONSTRAINT uq_simulated_trades_plan_hash UNIQUE (plan_hash)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_simulated_trades_forecast_run_id ON simulated_trades (forecast_run_id)"
    )
    op.execute(
        """
        CREATE TABLE simulated_trade_events (
            id                bigserial PRIMARY KEY,
            simulated_trade_id uuid NOT NULL
                REFERENCES simulated_trades(id) ON DELETE RESTRICT,
            state             text NOT NULL,
            event_timestamp   timestamptz NOT NULL,
            price             numeric,
            quantity          numeric,
            realized_pnl      numeric,
            costs             numeric,
            metadata          jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at        timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_simulated_trade_events_state CHECK
                (state IN ('PLANNED', 'OPEN', 'CLOSED', 'STOPPED', 'EXPIRED',
                           'CANCELLED_BEFORE_ENTRY', 'NO_TRADE')),
            CONSTRAINT ck_simulated_trade_events_metadata_object
                CHECK (jsonb_typeof(metadata) = 'object')
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_simulated_trade_events_trade_timestamp "
        "ON simulated_trade_events (simulated_trade_id, event_timestamp)"
    )
    op.execute(
        """
        CREATE TABLE paper_positions (
            id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            simulated_trade_id  uuid NOT NULL
                REFERENCES simulated_trades(id) ON DELETE RESTRICT,
            symbol              text NOT NULL,
            side                text NOT NULL,
            quantity            numeric NOT NULL,
            opened_at           timestamptz,
            entry_price         numeric,
            current_price       numeric,
            unrealized_pnl      numeric NOT NULL DEFAULT 0,
            closed_at           timestamptz,
            exit_price          numeric,
            realized_pnl        numeric NOT NULL DEFAULT 0,
            observed_at         timestamptz NOT NULL,
            CONSTRAINT ck_paper_positions_side CHECK (side IN ('LONG', 'SHORT')),
            CONSTRAINT ck_paper_positions_quantity_nonnegative CHECK (quantity >= 0)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_paper_positions_trade_observed_at "
        "ON paper_positions (simulated_trade_id, observed_at)"
    )
    op.execute(
        """
        CREATE TABLE portfolio_snapshots (
            id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            snapshot_timestamp timestamptz NOT NULL,
            cash               numeric NOT NULL,
            gross_exposure     numeric NOT NULL,
            net_exposure       numeric NOT NULL,
            equity             numeric NOT NULL,
            realized_pnl       numeric NOT NULL,
            unrealized_pnl     numeric NOT NULL,
            config_hash        text NOT NULL,
            created_at         timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_portfolio_snapshots_timestamp UNIQUE (snapshot_timestamp)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_portfolio_snapshots_timestamp_desc "
        "ON portfolio_snapshots (snapshot_timestamp DESC)"
    )


def _add_immutable_triggers() -> None:
    for table in _IMMUTABLE_TABLES:
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


def upgrade() -> None:
    _add_columns()
    _create_actuals()
    _create_evaluations()
    _create_simulator()
    _add_immutable_triggers()


def downgrade() -> None:
    for table in reversed(_IMMUTABLE_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table}")
    op.execute("DROP INDEX IF EXISTS uq_forecast_runs_request_hash")
    op.execute("DROP INDEX IF EXISTS uq_forecast_runs_idempotency_key")
    op.execute("DROP INDEX IF EXISTS uq_forecast_runs_content_hash")
    op.execute(
        """
        ALTER TABLE forecast_points
            DROP CONSTRAINT IF EXISTS ck_forecast_points_forecast_risk_nonnegative,
            DROP COLUMN IF EXISTS forecast_risk,
            DROP COLUMN IF EXISTS expected_abnormal_return
        """
    )
    op.execute(
        """
        ALTER TABLE forecast_runs
            DROP CONSTRAINT IF EXISTS ck_forecast_runs_recommended_horizon,
            DROP CONSTRAINT IF EXISTS ck_forecast_runs_ood_status,
            DROP CONSTRAINT IF EXISTS ck_forecast_runs_abstention_state,
            DROP CONSTRAINT IF EXISTS ck_forecast_runs_event_snapshot_object,
            DROP CONSTRAINT IF EXISTS ck_forecast_runs_feature_snapshot_object,
            DROP COLUMN IF EXISTS model_artifact_hash,
            DROP COLUMN IF EXISTS config_hash,
            DROP COLUMN IF EXISTS forecasting_engine_version,
            DROP COLUMN IF EXISTS recommended_horizon,
            DROP COLUMN IF EXISTS information_half_life,
            DROP COLUMN IF EXISTS ood_status,
            DROP COLUMN IF EXISTS abstention_state,
            DROP COLUMN IF EXISTS content_hash,
            DROP COLUMN IF EXISTS request_hash,
            DROP COLUMN IF EXISTS idempotency_key,
            DROP COLUMN IF EXISTS event_snapshot,
            DROP COLUMN IF EXISTS feature_snapshot
        """
    )
