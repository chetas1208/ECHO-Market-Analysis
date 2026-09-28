"""Alembic environment (async, asyncpg).

The URL is taken from ``config.attributes["database_url"]`` when set programmatically
(tests), otherwise from application settings (DATABASE_URL env var / root .env).
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings
from app.models import Base

config = context.config
if config.config_file_name and "database_url" not in config.attributes:
    fileConfig(config.config_file_name, disable_existing_loggers=False)
target_metadata = Base.metadata


def include_object(
    obj: object, name: str | None, type_: str, reflected: bool, compare_to: object
) -> bool:
    """Skip tables listed in ``config.attributes["exclude_tables"]`` (and their indexes).

    Unset for normal CLI use, so the default is to compare everything. Only the drift test
    sets it, to scope `alembic check` to specific tables.
    """
    excluded = config.attributes.get("exclude_tables") or ()
    if not excluded:
        return True
    table = name if type_ == "table" else getattr(getattr(obj, "table", None), "name", None)
    return table not in excluded


def _database_url() -> str:
    return config.attributes.get("database_url") or get_settings().database_url


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        include_object=include_object,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection, target_metadata=target_metadata, include_object=include_object
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(_database_url(), poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
