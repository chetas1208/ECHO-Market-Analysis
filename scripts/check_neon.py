#!/usr/bin/env python3
"""Read-only PostgreSQL connectivity check; never prints the connection URL."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import Settings


async def _check(settings: Settings) -> bool:
    connect_args: dict[str, object] = {"timeout": settings.db_pool_timeout}
    if settings.db_ssl_mode == "require":
        connect_args["ssl"] = True
    engine = create_async_engine(settings.database_url, connect_args=connect_args, pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return True
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict", action="store_true", help="fail when the database is not reachable")
    args = parser.parse_args()
    try:
        settings = Settings()
        ok = asyncio.run(_check(settings))
    except (ValidationError, SQLAlchemyError, OSError, TimeoutError, ImportError) as exc:
        print(f"Neon/PostgreSQL: ERROR ({type(exc).__name__})")
        return 1 if args.strict else 0
    print(f"Neon/PostgreSQL: {'OK' if ok else 'ERROR'}")
    return 0 if ok or not args.strict else 1


if __name__ == "__main__":
    raise SystemExit(main())
