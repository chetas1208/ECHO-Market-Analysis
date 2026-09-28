"""market_observations

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-20

OHLCV bars. `timeframe` defaults to '1m'; 5m/15m bars are derived in Day 2.
UNIQUE (symbol, timestamp, source, timeframe) makes appends idempotent.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE market_observations (
            id          bigserial PRIMARY KEY,
            symbol      text NOT NULL,
            timestamp   timestamptz NOT NULL,
            open        numeric NOT NULL,
            high        numeric NOT NULL,
            low         numeric NOT NULL,
            close       numeric NOT NULL,
            volume      numeric NOT NULL,
            vwap        numeric,
            trade_count bigint,
            source      text NOT NULL,
            timeframe   text NOT NULL DEFAULT '1m',
            created_at  timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_market_observations_symbol_nonempty CHECK (length(btrim(symbol)) > 0),
            CONSTRAINT ck_market_observations_source_nonempty CHECK (length(btrim(source)) > 0),
            CONSTRAINT ck_market_observations_timeframe_format
                CHECK (timeframe ~ '^[0-9]+[mhd]$'),
            CONSTRAINT ck_market_observations_prices_nonneg
                CHECK (open >= 0 AND high >= 0 AND low >= 0 AND close >= 0),
            CONSTRAINT ck_market_observations_high_low CHECK (high >= low),
            CONSTRAINT ck_market_observations_ohlc_within_range CHECK (
                high >= open AND high >= close AND low <= open AND low <= close
            ),
            CONSTRAINT ck_market_observations_volume_nonneg CHECK (volume >= 0),
            CONSTRAINT ck_market_observations_trade_count_nonneg
                CHECK (trade_count IS NULL OR trade_count >= 0),
            CONSTRAINT uq_market_observations_symbol_timestamp_source_timeframe
                UNIQUE (symbol, timestamp, source, timeframe)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_market_observations_symbol_timestamp "
        "ON market_observations (symbol, timestamp)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS market_observations")
