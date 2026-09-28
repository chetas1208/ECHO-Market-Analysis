"""Idempotent seeding of mock fixtures (reusable by the CLI and tests)."""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError
from app.fixtures.mock_events import MOCK_EVENTS
from app.services.events import EventService

logger = logging.getLogger("echo.seed")


async def seed_mock_events(session: AsyncSession) -> dict[str, str]:
    """Insert each mock event unless it exists. Returns {event_id: "created" | "skipped"}."""
    service = EventService(session)
    results: dict[str, str] = {}
    for fixture in MOCK_EVENTS:
        assert fixture.id is not None
        try:
            await service.create(fixture)
            results[fixture.id] = "created"
        except ConflictError:
            results[fixture.id] = "skipped"
    logger.info(
        "seed complete",
        extra={"operation": "seed.mock_events", "count": len(results)},
    )
    return results
