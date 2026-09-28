import asyncio

from alembic import command
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from tests.conftest import alembic_config, migrate_clean_database

TABLES = {"canonical_events", "forecast_runs", "forecast_points", "market_observations"}


async def _fetch(engine: AsyncEngine, sql: str, **params: object) -> list[tuple]:
    async with engine.connect() as conn:
        return [tuple(r) for r in (await conn.execute(text(sql), params)).all()]


async def test_migration_from_clean_creates_all_tables(engine: AsyncEngine) -> None:
    rows = await _fetch(
        engine,
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'",
    )
    assert {r[0] for r in rows} >= TABLES
    assert ("alembic_version",) in rows


async def test_expected_indexes_exist(engine: AsyncEngine) -> None:
    rows = await _fetch(
        engine,
        "SELECT c.relname, string_agg(a.attname, ', ' ORDER BY k.ord) "
        "FROM pg_index i "
        "JOIN pg_class c ON c.oid = i.indrelid "
        "JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = 'public' "
        "CROSS JOIN LATERAL unnest(i.indkey) WITH ORDINALITY AS k(attnum, ord) "
        "JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = k.attnum "
        "GROUP BY i.indexrelid, c.relname",
    )
    indexes = set(rows)
    assert ("canonical_events", "timestamp") in indexes
    assert ("canonical_events", "source_type") in indexes
    assert ("canonical_events", "event_type") in indexes
    assert ("forecast_runs", "symbol, prediction_timestamp") in indexes
    # served by the UNIQUE (forecast_run_id, horizon) constraint's index
    assert ("forecast_points", "forecast_run_id, horizon") in indexes
    assert ("market_observations", "symbol, timestamp") in indexes
    assert ("market_observations", "symbol, timestamp, source, timeframe") in indexes


async def test_immutability_triggers_and_fk_restrict_exist(engine: AsyncEngine) -> None:
    rows = await _fetch(
        engine,
        "SELECT c.relname, t.tgname, t.tgtype FROM pg_trigger t "
        "JOIN pg_class c ON c.oid = t.tgrelid "
        "WHERE NOT t.tgisinternal AND c.relname IN ('forecast_runs', 'forecast_points')",
    )
    by_table: dict[str, list[int]] = {}
    for table, _name, tgtype in rows:
        by_table.setdefault(table, []).append(tgtype)
    for table in ("forecast_runs", "forecast_points"):
        types = by_table[table]
        assert len(types) == 2
        # tgtype bits: 1 = ROW, 2 = BEFORE, 8 = DELETE, 16 = UPDATE, 32 = TRUNCATE
        row_trigger = next(t for t in types if t & 1)
        truncate_trigger = next(t for t in types if t & 32)
        assert row_trigger & 2 and row_trigger & 8 and row_trigger & 16
        assert truncate_trigger & 2 and not truncate_trigger & 1

    fks = await _fetch(
        engine,
        "SELECT conrelid::regclass::text, confrelid::regclass::text, confdeltype::text "
        "FROM pg_constraint WHERE contype = 'f'",
    )
    assert ("forecast_runs", "canonical_events", "r") in fks
    assert ("forecast_points", "forecast_runs", "r") in fks
    assert all(deltype != "c" for _, _, deltype in fks)  # no ON DELETE CASCADE anywhere


async def test_upgrade_downgrade_upgrade_roundtrip(scratch_db_url: str) -> None:
    # env.py drives its own event loop, so run the alembic commands in a worker thread.
    await asyncio.to_thread(migrate_clean_database, scratch_db_url)
    cfg = alembic_config(scratch_db_url)
    await asyncio.to_thread(command.downgrade, cfg, "base")

    eng = create_async_engine(scratch_db_url, poolclass=NullPool)
    try:
        rows = await _fetch(
            eng,
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'",
        )
        assert not TABLES & {r[0] for r in rows}
        await asyncio.to_thread(command.upgrade, cfg, "head")
        rows = await _fetch(
            eng,
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'",
        )
        assert {r[0] for r in rows} >= TABLES
    finally:
        await eng.dispose()
