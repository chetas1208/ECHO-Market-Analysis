"""DB-backed tests for WorldRepository and migration 0005.

Requires a unique TEST_DATABASE_URL (name ending ``_test``); skipped otherwise so the default
``echo_test`` database is never touched. Writes happen inside a connection-level transaction
that is rolled back per test (event_revisions is append-only and events with evidence cannot be
deleted, so nothing may be committed to the shared test database).
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

from app.repositories.world import (
    MAX_PAYLOAD_EXCERPT_CHARS,
    MAX_RECENT_FINGERPRINTS,
    WorldRepository,
)
from tests.conftest import alembic_config, migrate_clean_database

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="set a unique TEST_DATABASE_URL (…_test) to run DB-backed world tests",
)

T0 = datetime(2026, 9, 16, 9, 0, tzinfo=UTC)


@pytest_asyncio.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Session inside an outer transaction that is always rolled back."""
    async with engine.connect() as conn:
        outer = await conn.begin()
        s = AsyncSession(
            bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False
        )
        try:
            yield s
        finally:
            await s.close()
            await outer.rollback()


@pytest.fixture
def repo(session: AsyncSession) -> WorldRepository:
    return WorldRepository(session)


def new_id(prefix: str = "w") -> str:
    return f"evt_{prefix}_{uuid.uuid4().hex[:12]}"


async def make_event(session: AsyncSession, event_id: str | None = None, **over: object) -> str:
    event_id = event_id or new_id()
    params = {
        "id": event_id,
        "ts": T0,
        "title": "Test world event",
        "severity": 0.5,
        "novelty": 0.4,
        "corroboration": 0.3,
        "confidence": 0.6,
    }
    params.update(over)
    await session.execute(
        text(
            "INSERT INTO canonical_events (id, timestamp, source_type, event_type, title, "
            "severity, novelty, corroboration, confidence) "
            "VALUES (:id, :ts, 'WORLD', 'shipping_disruption', :title, :severity, :novelty, "
            ":corroboration, :confidence)"
        ),
        params,
    )
    return event_id


def source_row(n: int = 0, **over: object) -> dict[str, object]:
    row: dict[str, object] = {
        "provider": "replay",
        "source_name": f"Publisher {n}",
        "source_group": f"pub{n}",
        "source_url": f"https://example.test/{n}",
        "source_identifier": f"src-{n}",
        "headline": "Tanker traffic halted",
        "published_at": T0,
        "retrieved_at": T0 + timedelta(minutes=1),
        "is_independent": True,
        "syndicated_from": None,
        "reliability": 0.8,
        "content_hash": f"hash-{n}",
        "metadata": {"k": "v"},
    }
    row.update(over)
    return row


async def scalar(session: AsyncSession, sql: str, **params: object) -> object:
    return (await session.execute(text(sql), params)).scalar_one()


# --- event_sources -----------------------------------------------------------------------


async def test_add_source_idempotent_on_event_and_content_hash(
    session: AsyncSession, repo: WorldRepository
) -> None:
    eid = await make_event(session)
    assert await repo.add_source(eid, source_row(1)) is True
    assert await repo.add_source(eid, source_row(1, source_name="Other name")) is False
    assert await repo.add_source(eid, source_row(2)) is True
    await session.commit()
    sources = await repo.list_sources(eid)
    assert [s.content_hash for s in sources] == ["hash-1", "hash-2"]
    assert sources[0].source_name == "Publisher 1"  # first write wins
    assert sources[0].metadata_ == {"k": "v"}
    assert sources[0].published_at == T0 and sources[0].published_at.utcoffset() == timedelta(0)
    assert sources[0].reliability == pytest.approx(0.8)


async def test_same_content_hash_allowed_on_different_events(
    session: AsyncSession, repo: WorldRepository
) -> None:
    a, b = await make_event(session), await make_event(session)
    assert await repo.add_source(a, source_row(1)) is True
    assert await repo.add_source(b, source_row(1)) is True


async def test_add_source_rejects_unknown_fields_and_bad_reliability(
    session: AsyncSession, repo: WorldRepository
) -> None:
    eid = await make_event(session)
    with pytest.raises(ValueError, match="bogus"):
        await repo.add_source(eid, source_row(1, bogus=1))
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            await repo.add_source(eid, source_row(2, reliability=1.5))


async def test_add_source_unknown_event_violates_fk(
    session: AsyncSession, repo: WorldRepository
) -> None:
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            await repo.add_source("evt_does_not_exist", source_row(1))


async def test_find_by_provider_event_id(session: AsyncSession, repo: WorldRepository) -> None:
    a, b = await make_event(session), await make_event(session)
    await repo.add_source(a, source_row(1, source_identifier="wm-100"))
    await repo.add_source(b, source_row(2, source_identifier="wm-200"))
    assert await repo.find_by_provider_event_id("replay", "wm-100") == a
    assert await repo.find_by_provider_event_id("replay", "wm-200") == b
    assert await repo.find_by_provider_event_id("world_monitor", "wm-100") is None
    assert await repo.find_by_provider_event_id("replay", "nope") is None


# --- event_fingerprints ------------------------------------------------------------------


async def fp(repo: WorldRepository, eid: str, when: datetime, **over: object) -> None:
    args: dict[str, object] = {
        "fingerprint": "f" * 40,
        "event_class": "shipping_disruption",
        "location_key": "strait of hormuz",
        "time_bucket": 123,
        "entity_keys": ["b", "a"],
        "tokens": ["y", "x"],
        "occurred_at": when,
    }
    args.update(over)
    await repo.upsert_fingerprint(eid, **args)  # type: ignore[arg-type]


async def test_upsert_fingerprint_insert_then_update(
    session: AsyncSession, repo: WorldRepository
) -> None:
    eid = await make_event(session)
    await fp(repo, eid, T0)
    await fp(repo, eid, T0 + timedelta(hours=1), fingerprint="a" * 40, time_bucket=124)
    assert await scalar(session, "SELECT count(*) FROM event_fingerprints") == 1
    (row,) = await repo.recent_fingerprints(T0 - timedelta(days=1))
    assert row.event_id == eid and row.fingerprint == "a" * 40 and row.time_bucket == 124
    assert row.occurred_at == T0 + timedelta(hours=1)
    assert row.entity_keys == ["a", "b"] and row.tokens == ["x", "y"]  # stored sorted


async def test_recent_fingerprints_newest_first_since_and_limit(
    session: AsyncSession, repo: WorldRepository
) -> None:
    ids = [await make_event(session) for _ in range(5)]
    for i, eid in enumerate(ids):
        await fp(repo, eid, T0 + timedelta(hours=i))
    got = await repo.recent_fingerprints(T0 - timedelta(hours=1))
    assert [r.event_id for r in got] == list(reversed(ids))
    assert [r.event_id for r in await repo.recent_fingerprints(T0, limit=2)] == [ids[4], ids[3]]
    assert [r.event_id for r in await repo.recent_fingerprints(T0 + timedelta(hours=3))] == [
        ids[4],
        ids[3],
    ]
    assert len(await repo.recent_fingerprints(T0, limit=0)) == 1  # clamped up to 1
    assert await repo.recent_fingerprints(T0 + timedelta(days=1)) == []


async def test_recent_fingerprints_limit_capped_at_500(
    session: AsyncSession, repo: WorldRepository
) -> None:
    n = MAX_RECENT_FINGERPRINTS + 10
    await session.execute(
        text(
            "INSERT INTO canonical_events (id, timestamp, source_type, event_type, title, "
            "severity, novelty, corroboration, confidence) "
            "SELECT 'evt_bulk_' || g, :ts, 'WORLD', 'other', 't', 0, 0, 0, 0 "
            "FROM generate_series(1, :n) g"
        ),
        {"ts": T0, "n": n},
    )
    await session.execute(
        text(
            "INSERT INTO event_fingerprints (event_id, fingerprint, event_class, location_key, "
            "time_bucket, entity_keys, tokens, occurred_at) "
            "SELECT 'evt_bulk_' || g, 'f', 'other', 'unknown', 1, '[]'::jsonb, '[]'::jsonb, "
            "CAST(:ts AS timestamptz) + g * interval '1 minute' FROM generate_series(1, :n) g"
        ),
        {"ts": T0, "n": n},
    )
    got = await repo.recent_fingerprints(T0, limit=10_000)
    assert len(got) == MAX_RECENT_FINGERPRINTS
    assert got[0].event_id == f"evt_bulk_{n}"  # newest first


# --- event_revisions (append-only) -------------------------------------------------------


async def test_add_revision_roundtrip_and_duplicate_rejected(
    session: AsyncSession, repo: WorldRepository
) -> None:
    eid = await make_event(session)
    await repo.add_revision(eid, 1, {"severity": 0.5}, "merge:source_added")
    await repo.add_revision(eid, 2, {"severity": 0.6}, "merge:update")
    revs = await repo.list_revisions(eid)
    assert [(r.revision, r.snapshot, r.reason) for r in revs] == [
        (1, {"severity": 0.5}, "merge:source_added"),
        (2, {"severity": 0.6}, "merge:update"),
    ]
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            await repo.add_revision(eid, 2, {}, "dup")


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE event_revisions SET reason = 'tampered'",
        "DELETE FROM event_revisions",
        "TRUNCATE event_revisions",
    ],
)
@pytest.mark.parametrize("replica", [False, True])
async def test_event_revisions_immutable(
    session: AsyncSession, repo: WorldRepository, sql: str, replica: bool
) -> None:
    eid = await make_event(session)
    await repo.add_revision(eid, 1, {"a": 1}, "seed")
    if replica:
        try:
            async with session.begin_nested():
                await session.execute(text("SET LOCAL session_replication_role = replica"))
        except DBAPIError:
            pytest.skip("test role is not a superuser; cannot set session_replication_role")
        await session.execute(text("SET LOCAL session_replication_role = replica"))
    with pytest.raises(DBAPIError, match="immutable"):
        async with session.begin_nested():
            await session.execute(text(sql))
    if replica:
        await session.execute(text("SET LOCAL session_replication_role = origin"))
    assert await scalar(session, "SELECT reason FROM event_revisions") == "seed"


async def test_revision_triggers_are_enable_always(session: AsyncSession) -> None:
    rows = (
        await session.execute(
            text(
                "SELECT tgname, tgenabled::text, tgtype FROM pg_trigger t "
                "JOIN pg_class c ON c.oid = t.tgrelid "
                "WHERE NOT tgisinternal AND c.relname = 'event_revisions'"
            )
        )
    ).all()
    assert {r[0] for r in rows} == {
        "trg_event_revisions_immutable_row",
        "trg_event_revisions_immutable_truncate",
    }
    assert {r[1] for r in rows} == {"A"}
    by_name = {r[0]: r[2] for r in rows}
    row_t = by_name["trg_event_revisions_immutable_row"]
    trunc_t = by_name["trg_event_revisions_immutable_truncate"]
    # tgtype bits: 1 = ROW, 2 = BEFORE, 8 = DELETE, 16 = UPDATE, 32 = TRUNCATE
    assert row_t & 1 and row_t & 2 and row_t & 8 and row_t & 16
    assert trunc_t & 2 and trunc_t & 32 and not trunc_t & 1


# --- foreign keys ------------------------------------------------------------------------


async def test_all_new_fks_are_restrict(session: AsyncSession) -> None:
    fks = (
        await session.execute(
            text(
                "SELECT conrelid::regclass::text, confdeltype::text FROM pg_constraint "
                "WHERE contype = 'f' AND conrelid::regclass::text IN "
                "('event_sources', 'event_fingerprints', 'event_revisions', "
                "'event_relationships')"
            )
        )
    ).all()
    tables = [t for t, _ in fks]
    assert sorted(tables) == [
        "event_fingerprints",
        "event_relationships",
        "event_relationships",
        "event_revisions",
        "event_sources",
    ]
    assert {d for _, d in fks} == {"r"}


async def test_event_cannot_be_deleted_while_children_exist(
    session: AsyncSession, repo: WorldRepository
) -> None:
    for child in ("source", "fingerprint", "revision", "relationship"):
        eid, other = await make_event(session), await make_event(session)
        if child == "source":
            await repo.add_source(eid, source_row(1))
        elif child == "fingerprint":
            await fp(repo, eid, T0)
        elif child == "revision":
            await repo.add_revision(eid, 1, {}, "seed")
        else:
            await repo.add_relationship(eid, other, "RELATED", 0.5)
        with pytest.raises(IntegrityError):
            async with session.begin_nested():
                await session.execute(
                    text("DELETE FROM canonical_events WHERE id = :i"), {"i": eid}
                )
        assert (
            await scalar(session, "SELECT count(*) FROM canonical_events WHERE id = :i", i=eid) == 1
        )
        # an event with no children is still deletable
        await session.execute(text("DELETE FROM canonical_events WHERE id = :i"), {"i": new_id()})


# --- world_ingest_errors -----------------------------------------------------------------


async def test_record_ingest_error_caps_excerpt_and_strips_nul(
    session: AsyncSession, repo: WorldRepository
) -> None:
    big = "x" * 5000
    rid = await repo.record_ingest_error(
        provider="world_monitor", error="bad payload", payload_hash="h1", payload_excerpt=big
    )
    rid2 = await repo.record_ingest_error(
        provider="replay", error="boom", payload_excerpt="a\x00b'; DROP TABLE x;--"
    )
    rid3 = await repo.record_ingest_error(provider="replay", error="no payload")
    rows = {
        r[0]: r
        for r in (
            await session.execute(
                text(
                    "SELECT id, provider, error, payload_hash, payload_excerpt "
                    "FROM world_ingest_errors"
                )
            )
        ).all()
    }
    assert len(rows[rid][4]) == MAX_PAYLOAD_EXCERPT_CHARS == 500
    assert rows[rid][1:4] == ("world_monitor", "bad payload", "h1")
    assert rows[rid2][4] == "ab'; DROP TABLE x;--"
    assert rows[rid3][4] is None and rows[rid3][3] is None


async def test_db_rejects_oversized_excerpt(session: AsyncSession) -> None:
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            await session.execute(
                text(
                    "INSERT INTO world_ingest_errors (provider, error, payload_excerpt) "
                    "VALUES ('p', 'e', :x)"
                ),
                {"x": "y" * 501},
            )
    await session.execute(
        text(
            "INSERT INTO world_ingest_errors (provider, error, payload_excerpt) VALUES ('p','e',:x)"
        ),
        {"x": "y" * 500},
    )


# --- event_relationships -----------------------------------------------------------------


async def test_add_relationship_idempotent_and_checked(
    session: AsyncSession, repo: WorldRepository
) -> None:
    a, b = await make_event(session), await make_event(session)
    assert await repo.add_relationship(a, b, "POSSIBLE_CAUSE", 0.4) is True
    assert await repo.add_relationship(a, b, "POSSIBLE_CAUSE", 0.9) is False
    assert await repo.add_relationship(a, b, "REACTION_TO", 0.4) is True
    assert len(await repo.list_relationships(b)) == 2
    for args in ((a, b, "CAUSES", 0.5), (a, b, "RELATED", 1.5), (a, a, "RELATED", 0.5)):
        with pytest.raises(IntegrityError):
            async with session.begin_nested():
                await repo.add_relationship(*args)


# --- update_event_scores -----------------------------------------------------------------

UNTOUCHED = (
    "id, timestamp, source_type, event_type, title, summary, entities, companies, locations, "
    "source_refs, metadata, is_mock, created_at, ingested_at"
)


async def test_update_event_scores_sets_scores_and_updated_at_only(
    session: AsyncSession, repo: WorldRepository
) -> None:
    eid = await make_event(session)
    before_cols = (
        await session.execute(
            text(f"SELECT {UNTOUCHED} FROM canonical_events WHERE id = :i"), {"i": eid}
        )
    ).one()
    row0 = (
        await session.execute(
            text(
                "SELECT revision, updated_at, source_count, independent_source_count "
                "FROM canonical_events WHERE id = :i"
            ),
            {"i": eid},
        )
    ).one()
    assert tuple(row0) == (1, None, 1, 1)  # defaults

    ok = await repo.update_event_scores(
        eid,
        severity=0.9,
        novelty=0.1,
        corroboration=0.7,
        confidence=0.8,
        economic_channels={"oil_supply": -0.6, "energy_prices": 0.5},
        source_count=3,
        independent_source_count=2,
        revision=2,
    )
    assert ok is True
    after = (
        (await session.execute(text("SELECT * FROM canonical_events WHERE id = :i"), {"i": eid}))
        .mappings()
        .one()
    )
    assert (after["severity"], after["novelty"], after["corroboration"], after["confidence"]) == (
        0.9,
        0.1,
        0.7,
        0.8,
    )
    assert after["economic_channels"] == {"oil_supply": -0.6, "energy_prices": 0.5}
    assert (after["source_count"], after["independent_source_count"], after["revision"]) == (
        3,
        2,
        2,
    )
    first_updated = after["updated_at"]
    assert first_updated is not None
    after_cols = (
        await session.execute(
            text(f"SELECT {UNTOUCHED} FROM canonical_events WHERE id = :i"), {"i": eid}
        )
    ).one()
    assert tuple(after_cols) == tuple(before_cols)

    await repo.update_event_scores(
        eid, severity=0.9, novelty=0.1, corroboration=0.7, confidence=0.8,
        economic_channels={}, source_count=3, independent_source_count=2, revision=3,
    )  # fmt: skip
    second = await scalar(session, "SELECT updated_at FROM canonical_events WHERE id = :i", i=eid)
    assert second > first_updated  # type: ignore[operator]


async def test_update_event_scores_unknown_event_and_range_check(
    session: AsyncSession, repo: WorldRepository
) -> None:
    kw = dict(
        severity=0.5, novelty=0.5, corroboration=0.5, confidence=0.5,
        economic_channels={}, source_count=1, independent_source_count=1, revision=2,
    )  # fmt: skip
    assert await repo.update_event_scores("evt_missing", **kw) is False  # type: ignore[arg-type]
    eid = await make_event(session)
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            await repo.update_event_scores(eid, **{**kw, "severity": 1.5})  # type: ignore[arg-type]


# --- migration 0005 ----------------------------------------------------------------------

NEW_TABLES = {
    "event_sources",
    "event_fingerprints",
    "event_revisions",
    "event_relationships",
    "world_ingest_errors",
}
OLD_TABLES = {"canonical_events", "forecast_runs", "forecast_points", "market_observations"}
NEW_COLS = {"revision", "updated_at", "source_count", "independent_source_count"}
LEDGER_TRIGGERS = {
    "trg_forecast_runs_immutable_row",
    "trg_forecast_runs_immutable_truncate",
    "trg_forecast_points_immutable_row",
    "trg_forecast_points_immutable_truncate",
}


async def _state(eng: AsyncEngine) -> dict[str, object]:
    async with eng.connect() as conn:
        tables = set(
            (
                await conn.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'public'"
                    )
                )
            )
            .scalars()
            .all()
        )
        cols = set(
            (
                await conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'canonical_events'"
                    )
                )
            )
            .scalars()
            .all()
        )
        triggers = dict(
            (
                await conn.execute(
                    text("SELECT tgname, tgenabled::text FROM pg_trigger WHERE NOT tgisinternal")
                )
            ).all()
        )
        severity_idx = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM pg_indexes "
                    "WHERE indexname = 'ix_canonical_events_severity'"
                )
            )
        ).scalar_one()
        fn = (
            await conn.execute(
                text("SELECT count(*) FROM pg_proc WHERE proname = 'echo_forbid_ledger_mutation'")
            )
        ).scalar_one()
        version = (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar_one()
    return {
        "tables": tables,
        "cols": cols,
        "triggers": triggers,
        "severity_idx": severity_idx,
        "fn": fn,
        "version": version,
    }


async def test_alembic_check_clean_with_world_models(test_db_url: str) -> None:
    await asyncio.to_thread(command.check, alembic_config(test_db_url))


async def test_migration_0005_up_down_up(scratch_db_url: str) -> None:
    cfg = alembic_config(scratch_db_url)
    await asyncio.to_thread(migrate_clean_database, scratch_db_url)
    await asyncio.to_thread(command.upgrade, cfg, "0005")
    eng = create_async_engine(scratch_db_url, poolclass=NullPool)
    try:
        up = await _state(eng)
        assert up["tables"] >= NEW_TABLES and up["cols"] >= NEW_COLS  # type: ignore[operator]
        assert up["severity_idx"] == 1
        assert {up["triggers"][t] for t in LEDGER_TRIGGERS} == {"A"}  # type: ignore[index]
        assert up["triggers"]["trg_event_revisions_immutable_row"] == "A"  # type: ignore[index]

        # data present (children of an event + an append-only revision) must not block downgrade
        async with eng.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO canonical_events (id, timestamp, source_type, event_type, title, "
                    "severity, novelty, corroboration, confidence) "
                    "VALUES ('evt_mig_1', now(), 'WORLD', 'other', 't', 0, 0, 0, 0)"
                )
            )
            await conn.execute(
                text(
                    "INSERT INTO event_revisions (event_id, revision, snapshot, reason) "
                    "VALUES ('evt_mig_1', 1, '{}'::jsonb, 'seed')"
                )
            )
            await conn.execute(
                text(
                    "INSERT INTO event_sources (event_id, provider, source_name, retrieved_at, "
                    "is_independent, content_hash) VALUES ('evt_mig_1', 'p', 'n', now(), true, 'h')"
                )
            )

        await asyncio.to_thread(command.downgrade, cfg, "0004")
        down = await _state(eng)
        assert not NEW_TABLES & down["tables"]  # type: ignore[operator]
        assert not NEW_COLS & down["cols"]  # type: ignore[operator]
        assert down["severity_idx"] == 0
        assert down["tables"] >= OLD_TABLES  # type: ignore[operator]
        assert down["version"] == "0004"
        assert down["fn"] == 1  # 0002's trigger function survives
        assert {down["triggers"][t] for t in LEDGER_TRIGGERS} == {"A"}  # type: ignore[index]
        assert not [t for t in down["triggers"] if "event_revisions" in t]  # type: ignore[attr-defined]
        async with eng.connect() as conn:  # existing event survives the downgrade
            assert (
                await conn.execute(
                    text("SELECT count(*) FROM canonical_events WHERE id='evt_mig_1'")
                )
            ).scalar_one() == 1

        await asyncio.to_thread(command.upgrade, cfg, "0005")
        again = await _state(eng)
        assert again["tables"] >= NEW_TABLES and again["cols"] >= NEW_COLS  # type: ignore[operator]
        assert again["triggers"]["trg_event_revisions_immutable_truncate"] == "A"  # type: ignore[index]
        async with eng.connect() as conn:  # defaults backfilled onto the pre-existing row
            row = (
                await conn.execute(
                    text(
                        "SELECT revision, updated_at, source_count, independent_source_count "
                        "FROM canonical_events WHERE id = 'evt_mig_1'"
                    )
                )
            ).one()
        assert tuple(row) == (1, None, 1, 1)
    finally:
        await eng.dispose()
