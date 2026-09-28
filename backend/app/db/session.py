"""Async engine / session factory wiring. Schema is managed only by Alembic."""

import time
from collections.abc import AsyncIterator

import asyncpg
from fastapi import FastAPI, Request
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings


def create_engine(settings: Settings) -> AsyncEngine:
    connect_args: dict[str, object] = {"timeout": settings.db_pool_timeout}
    if settings.db_ssl_mode == "require":
        # asyncpg accepts a boolean SSL requirement and leaves certificate
        # verification to the provider's standard TLS configuration.
        connect_args["ssl"] = True
    return create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout,
        pool_recycle=settings.db_pool_recycle,
        connect_args=connect_args,
    )


def init_db(app: FastAPI, settings: Settings) -> None:
    app.state.engine = create_engine(settings)
    app.state.session_factory = async_sessionmaker(app.state.engine, expire_on_commit=False)


async def close_db(app: FastAPI) -> None:
    engine: AsyncEngine | None = getattr(app.state, "engine", None)
    if engine is not None:
        await engine.dispose()


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    metrics = getattr(request.app.state, "metrics", None)
    started = time.perf_counter()
    async with request.app.state.session_factory() as session:
        if metrics is not None:
            session.info["metrics"] = metrics
        try:
            yield session
        finally:
            if metrics is not None:
                metrics.observe(
                    "echo_db_session_duration_seconds",
                    time.perf_counter() - started,
                    help_text="Database session dependency duration in seconds.",
                )


# Raised by the driver (not wrapped by SQLAlchemy) when the server cannot be reached or a
# connection attempt is rejected.
DB_CONNECTIVITY_ERRORS: tuple[type[BaseException], ...] = (
    OSError,  # includes ConnectionError and TimeoutError
    asyncpg.PostgresError,
    asyncpg.InterfaceError,
)
