"""Day 9 paper execution intents, fills, transitions, and reconciliation."""

from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_IMMUTABLE_TABLES = (
    "order_intents",
    "execution_fills",
    "execution_events",
    "broker_reconciliations",
)


def upgrade() -> None:
    op.execute("""
        CREATE TABLE order_intents (
            id uuid PRIMARY KEY,
            decision_id text NOT NULL,
            forecast_id text NOT NULL,
            strategy_version text NOT NULL,
            config_hash text NOT NULL,
            symbol text NOT NULL,
            side text NOT NULL,
            quantity numeric,
            notional numeric,
            order_type text NOT NULL DEFAULT 'MARKET',
            time_in_force text NOT NULL DEFAULT 'DAY',
            limit_price numeric,
            stop_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
            hedge_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            idempotency_key text NOT NULL,
            execution_source text NOT NULL,
            state text NOT NULL,
            external_order_id text,
            rejection_reason text,
            content_hash text NOT NULL,
            CONSTRAINT ck_order_intents_side CHECK (side IN ('LONG', 'SHORT')),
            CONSTRAINT ck_order_intents_source CHECK (execution_source IN ('REPLAY', 'PAPER')),
            CONSTRAINT ck_order_intents_state CHECK (state IN (
                'CREATED', 'SUBMITTING', 'SUBMITTED', 'PARTIALLY_FILLED',
                'FILLED', 'CANCELLED', 'REJECTED', 'EXPIRED', 'FAILED',
                'REJECTED_PRE_EXECUTION')),
            CONSTRAINT ck_order_intents_stop_metadata_object CHECK
                (jsonb_typeof(stop_metadata) = 'object'),
            CONSTRAINT ck_order_intents_hedge_metadata_object CHECK
                (jsonb_typeof(hedge_metadata) = 'object'),
            CONSTRAINT uq_order_intents_idempotency_key UNIQUE (idempotency_key)
        )
    """)
    op.execute("CREATE INDEX ix_order_intents_decision_id ON order_intents (decision_id)")
    op.execute("""
        CREATE TABLE execution_fills (
            id bigserial PRIMARY KEY,
            order_intent_id uuid NOT NULL REFERENCES order_intents(id) ON DELETE RESTRICT,
            external_order_id text NOT NULL,
            external_fill_id text NOT NULL,
            timestamp timestamptz NOT NULL,
            quantity numeric NOT NULL,
            price numeric NOT NULL,
            fees numeric NOT NULL DEFAULT 0,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_execution_fills_quantity_positive CHECK (quantity > 0),
            CONSTRAINT ck_execution_fills_price_positive CHECK (price > 0),
            CONSTRAINT uq_execution_fills_external_fill_id UNIQUE (external_fill_id)
        )
    """)
    op.execute(
        "CREATE INDEX ix_execution_fills_order_intent "
        "ON execution_fills (order_intent_id, timestamp)"
    )
    op.execute("""
        CREATE TABLE execution_events (
            id bigserial PRIMARY KEY,
            order_intent_id uuid NOT NULL REFERENCES order_intents(id) ON DELETE RESTRICT,
            state text NOT NULL,
            event_timestamp timestamptz NOT NULL,
            metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_execution_events_metadata_object CHECK (jsonb_typeof(metadata) = 'object')
        )
    """)
    op.execute(
        "CREATE INDEX ix_execution_events_intent_timestamp "
        "ON execution_events (order_intent_id, event_timestamp)"
    )
    op.execute("""
        CREATE TABLE broker_reconciliations (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            provider text NOT NULL,
            observed_at timestamptz NOT NULL,
            state text NOT NULL,
            discrepancies jsonb NOT NULL DEFAULT '[]'::jsonb,
            account_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
            CONSTRAINT ck_broker_reconciliations_discrepancies_array CHECK
                (jsonb_typeof(discrepancies) = 'array')
        )
    """)
    for table in _IMMUTABLE_TABLES:
        op.execute(
            f"CREATE TRIGGER trg_{table}_immutable_row "
            f"BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW "
            "EXECUTE FUNCTION echo_forbid_ledger_mutation()"
        )
        op.execute(
            f"CREATE TRIGGER trg_{table}_immutable_truncate "
            f"BEFORE TRUNCATE ON {table} FOR EACH STATEMENT "
            "EXECUTE FUNCTION echo_forbid_ledger_mutation()"
        )


def downgrade() -> None:
    for table in reversed(_IMMUTABLE_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table}")
