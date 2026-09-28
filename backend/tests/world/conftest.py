"""World unit tests are pure (no DB) by default.

Overrides the Day 1 autouse fixture that cleans DB tables, so these tests never touch
PostgreSQL and parallel runs cannot collide. DB-backed world tests must set a unique
TEST_DATABASE_URL (name ending in ``_test``) and request the ``engine`` fixture explicitly.
"""

import pytest_asyncio


@pytest_asyncio.fixture(autouse=True)
async def _clean_mutable_tables():
    yield
