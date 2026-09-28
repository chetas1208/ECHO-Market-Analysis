"""market extras: received_at, lookup index, timeframe allow-list, ledger trigger hardening

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-20

- market_observations.received_at: when ECHO received the bar (nullable; NULL for backfills).
- Index (symbol, timeframe, timestamp DESC) serves get_bars / load_recent / latest_timestamp.
- CHECK timeframe IN ('1m','5m','15m'). The constraint name sorts AFTER
  ck_market_observations_timeframe_format so a malformed timeframe such as 'weekly' still
  reports the format constraint first (Postgres evaluates CHECKs in name order).
- Superuser-bypass repair: plain ENABLE TRIGGER only fires in origin/local mode, so a
  superuser running ``SET session_replication_role = replica`` could UPDATE/DELETE/TRUNCATE
  the immutable ledger. ENABLE ALWAYS TRIGGER makes the immutability triggers fire in every
  session_replication_role. Downgrade restores the default (origin/local only) state.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEDGER_TABLES = ("forecast_runs", "forecast_points")


def _triggers() -> list[tuple[str, str]]:
    return [(t, f"trg_{t}_immutable_{kind}") for t in LEDGER_TABLES for kind in ("row", "truncate")]


def upgrade() -> None:
    op.execute("ALTER TABLE market_observations ADD COLUMN received_at timestamptz")
    op.execute(
        "CREATE INDEX ix_market_observations_symbol_timeframe_timestamp_desc "
        "ON market_observations (symbol, timeframe, timestamp DESC)"
    )
    op.execute(
        "ALTER TABLE market_observations ADD CONSTRAINT ck_market_observations_timeframe_supported "
        "CHECK (timeframe IN ('1m', '5m', '15m'))"
    )
    for table, trigger in _triggers():
        op.execute(f"ALTER TABLE {table} ENABLE ALWAYS TRIGGER {trigger}")


def downgrade() -> None:
    for table, trigger in _triggers():
        op.execute(f"ALTER TABLE {table} ENABLE TRIGGER {trigger}")
    op.execute(
        "ALTER TABLE market_observations "
        "DROP CONSTRAINT IF EXISTS ck_market_observations_timeframe_supported"
    )
    op.execute("DROP INDEX IF EXISTS ix_market_observations_symbol_timeframe_timestamp_desc")
    op.execute("ALTER TABLE market_observations DROP COLUMN IF EXISTS received_at")
