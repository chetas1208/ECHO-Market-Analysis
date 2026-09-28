"""Seed the mock world event: ``python -m app.scripts.seed`` (run from backend/)."""

import asyncio
import sys

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import create_engine
from app.services.seed import seed_mock_events


async def main() -> int:
    settings = get_settings()
    configure_logging(settings.log_level, settings.service_name)
    engine = create_engine(settings)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            results = await seed_mock_events(session)
    finally:
        await engine.dispose()
    for event_id, outcome in results.items():
        print(f"{outcome}: {event_id}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
