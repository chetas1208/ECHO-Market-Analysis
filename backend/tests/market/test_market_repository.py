"""DB-backed tests for MarketBarRepository and migration 0004.

Requires a unique TEST_DATABASE_URL (name ending ``_test``); skipped otherwise so the default
``echo_test`` database is never touched from this module.
"""

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from alembic import command
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.market.types import Bar, Interval, ProviderName
from app.repositories.market import MAX_BARS_LIMIT, UPSERT_CHUNK_SIZE, MarketBarRepository
from tests.conftest import alembic_config, migrate_clean_database

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="set a unique TEST_DATABASE_URL (…_test) to run DB-backed market tests",
)

T0 = datetime(2026, 9, 21, 14, 30, tzinfo=UTC)


def bar(
    i: int = 0,
    *,
    symbol: str = "NVDA",
    interval: Interval = Interval.M1,
    source: ProviderName = ProviderName.REPLAY,
    close: float = 100.5,
    **kw: object,
) -> Bar:
    ts = T0 + timedelta(minutes=i * interval.minutes)
    fields: dict[str, object] = {
        "symbol": symbol,
        "timestamp": ts,
        "interval": interval,
        "open": 100.0,
        "high": max(101.0, close),
        "low": min(99.0, close),
        "close": close,
        "volume": 1000.0 + i,
        "source": source,
    }
    fields.update(kw)
    return Bar(**fields)


@pytest_asyncio.fixture(autouse=True)
async def _clean_bars(engine: AsyncEngine) -> AsyncIterator[None]:
    async def clean() -> None:
        async with engine.begin() as conn:
            await conn.execute(text("TRUNCATE market_observations"))

    await clean()
    yield
    await clean()


@pytest_asyncio.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    async with AsyncSession(engine, expire_on_commit=False) as s:
        yield s


async def count(engine: AsyncEngine, where: str = "true") -> int:
    async with engine.connect() as conn:
        return (
            await conn.execute(text(f"SELECT count(*) FROM market_observations WHERE {where}"))
        ).scalar_one()


async def test_upsert_empty_returns_zero(session: AsyncSession) -> None:
    assert await MarketBarRepository(session).upsert_bars([]) == 0


async def test_upsert_idempotent_same_bar_twice(session: AsyncSession, engine: AsyncEngine) -> None:
    repo = MarketBarRepository(session)
    assert await repo.upsert_bars([bar(0)]) == 1
    assert await repo.upsert_bars([bar(0)]) == 1  # conflict path also counts as affected
    await session.commit()
    assert await count(engine) == 1


async def test_upsert_duplicates_within_batch_collapse_last_wins(
    session: AsyncSession, engine: AsyncEngine
) -> None:
    repo = MarketBarRepository(session)
    assert await repo.upsert_bars([bar(0, close=100.2), bar(0, close=100.9)]) == 1
    await session.commit()
    (got,) = await repo.get_bars("NVDA", Interval.M1)
    assert got.close == pytest.approx(100.9)


async def test_update_on_conflict_changes_values(session: AsyncSession) -> None:
    repo = MarketBarRepository(session)
    await repo.upsert_bars([bar(0, close=100.5)])
    recv = T0 + timedelta(minutes=2)
    await repo.upsert_bars(
        [bar(0, close=100.8, volume=5555.0, vwap=100.4, trade_count=12, received_at=recv)]
    )
    await session.commit()
    (got,) = await repo.get_bars("NVDA", Interval.M1)
    assert got.close == pytest.approx(100.8)
    assert got.volume == pytest.approx(5555.0)
    assert got.vwap == pytest.approx(100.4)
    assert got.trade_count == 12
    assert got.received_at == recv


async def test_different_source_or_interval_separate_rows(
    session: AsyncSession, engine: AsyncEngine
) -> None:
    repo = MarketBarRepository(session)
    n = await repo.upsert_bars(
        [
            bar(0, source=ProviderName.REPLAY),
            bar(0, source=ProviderName.MASSIVE),
            bar(0, source=ProviderName.ALPACA),
            bar(0, interval=Interval.M5),
        ]
    )
    await session.commit()
    assert n == 4
    assert await count(engine) == 4
    both = await repo.get_bars("NVDA", Interval.M1)
    assert {b.source for b in both} == {
        ProviderName.REPLAY,
        ProviderName.MASSIVE,
        ProviderName.ALPACA,
    }


async def test_large_upsert_is_chunked(session: AsyncSession, engine: AsyncEngine) -> None:
    n = UPSERT_CHUNK_SIZE * 2 + 37
    bars = [bar(i) for i in range(n)]
    assert await MarketBarRepository(session).upsert_bars(bars) == n
    await session.commit()
    assert await count(engine) == n


async def test_get_bars_ascending_and_roundtrip_fields(session: AsyncSession) -> None:
    repo = MarketBarRepository(session)
    recv = T0 + timedelta(seconds=90)
    src = [bar(i, vwap=100.1, trade_count=7 + i, received_at=recv) for i in (3, 0, 2, 1)]
    await repo.upsert_bars(src)
    await session.commit()
    got = await repo.get_bars("nvda", Interval.M1)  # symbol lookup is case-insensitive
    assert [b.timestamp for b in got] == [T0 + timedelta(minutes=i) for i in range(4)]
    assert got[1] == bar(1, vwap=100.1, trade_count=8, received_at=recv)
    assert got[0].interval is Interval.M1
    assert got[0].source is ProviderName.REPLAY


async def test_timestamps_returned_utc_aware(session: AsyncSession) -> None:
    repo = MarketBarRepository(session)
    await repo.upsert_bars([bar(0, received_at=T0)])
    await session.commit()
    (got,) = await repo.get_bars("NVDA", Interval.M1)
    assert got.timestamp.tzinfo is not None
    assert got.timestamp.utcoffset() == timedelta(0)
    assert got.received_at is not None and got.received_at.utcoffset() == timedelta(0)
    assert (await repo.latest_timestamp("NVDA")).utcoffset() == timedelta(0)
    (recent,) = await repo.load_recent("NVDA", Interval.M1, 1)
    assert recent.timestamp == T0


async def test_get_bars_filters_start_end_inclusive_and_interval_symbol(
    session: AsyncSession,
) -> None:
    repo = MarketBarRepository(session)
    await repo.upsert_bars(
        [bar(i) for i in range(10)]
        + [bar(i, symbol="SPY") for i in range(10)]
        + [bar(i, interval=Interval.M5) for i in range(3)]
    )
    await session.commit()
    start, end = T0 + timedelta(minutes=2), T0 + timedelta(minutes=5)
    got = await repo.get_bars("NVDA", Interval.M1, start=start, end=end)
    assert [b.timestamp for b in got] == [T0 + timedelta(minutes=i) for i in (2, 3, 4, 5)]
    assert {b.symbol for b in got} == {"NVDA"}
    assert len(await repo.get_bars("NVDA", Interval.M1, start=start)) == 8
    assert len(await repo.get_bars("NVDA", Interval.M1, end=start)) == 3
    assert len(await repo.get_bars("NVDA", Interval.M5)) == 3
    assert await repo.get_bars("NOPE", Interval.M1) == []


async def test_get_bars_limit_default_small_and_hard_cap(session: AsyncSession) -> None:
    repo = MarketBarRepository(session)
    n = MAX_BARS_LIMIT + 50
    await repo.upsert_bars([bar(i) for i in range(n)])
    await session.commit()
    assert len(await repo.get_bars("NVDA", Interval.M1)) == 500  # default
    assert len(await repo.get_bars("NVDA", Interval.M1, limit=10)) == 10
    assert len(await repo.get_bars("NVDA", Interval.M1, limit=10_000)) == MAX_BARS_LIMIT
    assert len(await repo.get_bars("NVDA", Interval.M1, limit=0)) == 1  # clamped to >= 1


async def test_load_recent_returns_latest_n_ascending(session: AsyncSession) -> None:
    repo = MarketBarRepository(session)
    await repo.upsert_bars([bar(i) for i in range(20)])
    await session.commit()
    got = await repo.load_recent("NVDA", Interval.M1, 5)
    assert [b.timestamp for b in got] == [T0 + timedelta(minutes=i) for i in range(15, 20)]
    assert len(await repo.load_recent("NVDA", Interval.M1, 500)) == 20
    assert await repo.load_recent("NVDA", Interval.M1, 0) == []
    assert await repo.load_recent("NOPE", Interval.M1, 5) == []


async def test_latest_timestamp(session: AsyncSession) -> None:
    repo = MarketBarRepository(session)
    assert await repo.latest_timestamp() is None
    assert await repo.latest_timestamp("NVDA") is None
    await repo.upsert_bars([bar(i) for i in range(3)] + [bar(9, symbol="SPY")])
    await session.commit()
    assert await repo.latest_timestamp("NVDA") == T0 + timedelta(minutes=2)
    assert await repo.latest_timestamp("SPY") == T0 + timedelta(minutes=9)
    assert await repo.latest_timestamp() == T0 + timedelta(minutes=9)


async def test_unsupported_timeframe_rejected_by_check(engine: AsyncEngine) -> None:
    insert = text(
        "INSERT INTO market_observations "
        "(symbol, timestamp, open, high, low, close, volume, source, timeframe) "
        "VALUES ('X', now(), 1, 1, 1, 1, 0, 'replay', :tf)"
    )
    async with engine.connect() as conn:
        with pytest.raises(IntegrityError, match="timeframe_supported"):
            await conn.execute(insert, {"tf": "1h"})  # passes the format check, not the allow-list
        await conn.rollback()
        with pytest.raises(IntegrityError, match="timeframe_format"):
            await conn.execute(insert, {"tf": "weekly"})  # format check still reported first
        await conn.rollback()


async def test_received_at_column_and_desc_index_exist(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        col = (
            await conn.execute(
                text(
                    "SELECT is_nullable, data_type FROM information_schema.columns "
                    "WHERE table_name = 'market_observations' AND column_name = 'received_at'"
                )
            )
        ).one()
        idx = (
            await conn.execute(
                text(
                    "SELECT indexdef FROM pg_indexes WHERE indexname = "
                    "'ix_market_observations_symbol_timeframe_timestamp_desc'"
                )
            )
        ).scalar_one()
    assert tuple(col) == ("YES", "timestamp with time zone")
    assert '(symbol, timeframe, "timestamp" DESC)' in idx or "timestamp DESC" in idx


# --- migration 0004 round-trip + superuser-bypass repair -----------------------------------

TRIGGERS = [
    ("forecast_runs", "trg_forecast_runs_immutable_row"),
    ("forecast_runs", "trg_forecast_runs_immutable_truncate"),
    ("forecast_points", "trg_forecast_points_immutable_row"),
    ("forecast_points", "trg_forecast_points_immutable_truncate"),
]


async def trigger_modes(eng: AsyncEngine) -> dict[str, str]:
    async with eng.connect() as conn:
        rows = await conn.execute(
            text("SELECT tgname, tgenabled::text FROM pg_trigger WHERE NOT tgisinternal")
        )
        return {name: mode for name, mode in rows.all()}


async def schema_state(eng: AsyncEngine) -> dict[str, object]:
    async with eng.connect() as conn:
        cols = (
            (
                await conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'market_observations'"
                    )
                )
            )
            .scalars()
            .all()
        )
        idx = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM pg_indexes WHERE indexname = "
                    "'ix_market_observations_symbol_timeframe_timestamp_desc'"
                )
            )
        ).scalar_one()
        chk = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM pg_constraint WHERE conname = "
                    "'ck_market_observations_timeframe_supported'"
                )
            )
        ).scalar_one()
    return {
        "received_at": "received_at" in cols,
        "index": idx,
        "check": chk,
        "modes": await trigger_modes(eng),
    }


async def test_migration_0004_up_down_up_round_trip(scratch_db_url: str) -> None:
    await asyncio.to_thread(migrate_clean_database, scratch_db_url)  # base -> head (includes 0004)
    eng = create_async_engine(scratch_db_url, poolclass=NullPool)
    try:
        up = await schema_state(eng)
        assert up["received_at"] and up["index"] == 1 and up["check"] == 1
        assert {up["modes"][t] for _, t in TRIGGERS} == {"A"}

        await asyncio.to_thread(command.downgrade, alembic_config(scratch_db_url), "0003")
        down = await schema_state(eng)
        assert not down["received_at"] and down["index"] == 0 and down["check"] == 0
        assert {down["modes"][t] for _, t in TRIGGERS} == {"O"}  # REPLICA-only default restored

        await asyncio.to_thread(command.upgrade, alembic_config(scratch_db_url), "head")
        assert await schema_state(eng) == up
    finally:
        await eng.dispose()


REPLICA_SQL = [
    "UPDATE forecast_points SET q50 = q50",
    "UPDATE forecast_runs SET model_version = 'tampered'",
    "DELETE FROM forecast_points",
    "DELETE FROM forecast_runs",
    "TRUNCATE forecast_points",
    "TRUNCATE forecast_runs CASCADE",
]


async def _insert_run_and_point(conn) -> None:
    run_id = uuid.uuid4()
    await conn.execute(
        text(
            "INSERT INTO forecast_runs (id, symbol, prediction_timestamp, data_cutoff_at, "
            "model_version, feature_version) VALUES (:id, 'XOM', :t, :t, 'm', 'f')"
        ),
        {"id": run_id, "t": T0},
    )
    await conn.execute(
        text(
            "INSERT INTO forecast_points (forecast_run_id, horizon, horizon_trading_days, "
            "target_timestamp, q10, q50, q90, probability_positive) "
            "VALUES (:r, '1D', 1, :t, -0.02, 0.01, 0.04, 0.6)"
        ),
        {"r": run_id, "t": T0 + timedelta(days=1)},
    )


@pytest.mark.parametrize("sql", REPLICA_SQL)
async def test_ledger_immutable_even_under_replica_role(engine: AsyncEngine, sql: str) -> None:
    async with engine.connect() as conn:
        is_super = (
            await conn.execute(text("SELECT rolsuper FROM pg_roles WHERE rolname = current_user"))
        ).scalar_one()
    assert is_super, "test must run as superuser to exercise the bypass"
    async with engine.connect() as conn:
        outer = await conn.begin()
        try:
            await conn.execute(text("SET LOCAL session_replication_role = replica"))
            await _insert_run_and_point(conn)  # inserts are allowed
            with pytest.raises(DBAPIError, match="immutable"):
                async with conn.begin_nested():
                    await conn.execute(text(sql))
        finally:
            await outer.rollback()
    async with engine.connect() as conn:  # nothing leaked
        assert (await conn.execute(text("SELECT count(*) FROM forecast_runs"))).scalar_one() == 0


async def test_replica_bypass_exists_without_0004(scratch_db_url: str) -> None:
    """Control: at revision 0003 the same replica-mode UPDATE silently succeeds."""
    await asyncio.to_thread(migrate_clean_database, scratch_db_url)
    await asyncio.to_thread(command.downgrade, alembic_config(scratch_db_url), "0003")
    eng = create_async_engine(scratch_db_url, poolclass=NullPool)
    try:
        async with eng.connect() as conn:
            outer = await conn.begin()
            try:
                await conn.execute(text("SET LOCAL session_replication_role = replica"))
                await _insert_run_and_point(conn)
                result = await conn.execute(text("UPDATE forecast_points SET q50 = 0.02"))
                assert result.rowcount == 1  # bypass demonstrated
            finally:
                await outer.rollback()
    finally:
        await eng.dispose()
        await asyncio.to_thread(command.upgrade, alembic_config(scratch_db_url), "head")
