"""Test harness: a real PostgreSQL test database, migrated from clean with Alembic.

The test database (``<POSTGRES_DB>_test`` on the same server, or TEST_DATABASE_URL) is dropped
and recreated once per pytest session, then migrated programmatically. The immutable ledger
tables reject TRUNCATE/DELETE by design, so tests that write to them do so inside a
transaction that is rolled back, and per-test cleanup only touches canonical_events and
market_observations.
"""

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import asyncpg
import httpx
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings, get_settings
from app.db.session import close_db, init_db
from app.main import create_app

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _test_database_url() -> str:
    explicit = os.environ.get("TEST_DATABASE_URL")
    if explicit:
        url = make_url(explicit)
    else:
        base = make_url(get_settings().database_url)
        url = base.set(database=f"{base.database}_test")
    if not (url.database or "").endswith("_test"):
        raise RuntimeError(f"Refusing to run tests against non-test database {url.database!r}")
    return url.render_as_string(hide_password=False)


def asyncpg_dsn(sqlalchemy_url: str, database: str | None = None) -> str:
    url = make_url(sqlalchemy_url).set(drivername="postgresql")
    if database:
        url = url.set(database=database)
    return url.render_as_string(hide_password=False)


async def recreate_database(url: str) -> None:
    name = make_url(url).database
    assert name
    assert name.endswith("_test"), "refusing to drop a non-test database"
    conn = await asyncpg.connect(asyncpg_dsn(url, database="postgres"))
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await conn.execute(f'CREATE DATABASE "{name}"')
    finally:
        await conn.close()


def alembic_config(url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.attributes["database_url"] = url
    return cfg


def migrate_clean_database(url: str) -> None:
    """Drop/create the database, then run `alembic upgrade head` from empty."""
    asyncio.run(recreate_database(url))
    command.upgrade(alembic_config(url), "head")


@pytest.fixture(scope="session")
def test_db_url() -> Iterator[str]:
    url = _test_database_url()
    migrate_clean_database(url)
    yield url


@pytest.fixture(scope="session")
def scratch_db_url(test_db_url: str) -> str:
    """A second throwaway database for migration up/down tests."""
    url = make_url(test_db_url)
    name = f"{url.database.removesuffix('_test')}_migrations_test"
    return url.set(database=name).render_as_string(hide_password=False)


@pytest.fixture(scope="session")
def test_settings(test_db_url: str) -> Settings:
    return Settings(_env_file=None, database_url=test_db_url, log_level="WARNING")


@pytest_asyncio.fixture
async def engine(test_db_url: str) -> AsyncIterator[AsyncEngine]:
    eng = create_async_engine(test_db_url, poolclass=NullPool)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture(autouse=True)
async def _clean_mutable_tables(engine: AsyncEngine) -> AsyncIterator[None]:
    """Reset events and market data around each test.

    Ledger tables are never written permanently by tests (only inside rolled-back
    transactions), so deleting events cannot hit the RESTRICT foreign key.
    """

    async def clean() -> None:
        async with engine.begin() as conn:
            await conn.execute(text("TRUNCATE market_observations"))
            await conn.execute(text("DELETE FROM canonical_events"))

    await clean()
    yield
    await clean()


@pytest_asyncio.fixture
async def client(test_settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(test_settings, manage_db=False)
    init_db(app, test_settings)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http
    await close_db(app)


def unique_event_id(prefix: str = "test") -> str:
    return f"evt_{prefix}_{uuid.uuid4().hex[:12]}"


def event_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "timestamp": "2026-09-20T17:00:00Z",
        "source_type": "world",
        "event_type": "supply_disruption",
        "title": "Test event",
        "severity": 0.5,
        "novelty": 0.4,
        "corroboration": 0.3,
        "confidence": 0.9,
    }
    payload.update(overrides)
    return payload
