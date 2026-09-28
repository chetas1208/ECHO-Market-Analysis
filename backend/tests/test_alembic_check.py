"""`alembic check` must report no model/migration drift (indexes, uniques, columns)."""

import asyncio

from alembic import command

from tests.conftest import alembic_config


async def test_alembic_check_reports_no_drift(test_db_url: str) -> None:
    cfg = alembic_config(test_db_url)
    # env.py drives its own event loop, so run alembic in a worker thread.
    await asyncio.to_thread(command.check, cfg)
