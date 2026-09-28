"""Event business logic: id generation, source_type mapping, error translation."""

import logging
import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, DatabaseError, NotFoundError
from app.models import CanonicalEvent, EventSource
from app.repositories.events import EventRepository
from app.repositories.world import WorldRepository
from app.schemas.event import EventCreate, SourceType
from app.world.taxonomy import CATEGORY_GROUP

logger = logging.getLogger("echo.events")

EVENT_CATEGORIES: tuple[str, ...] = tuple(sorted(set(CATEGORY_GROUP.values())))


def event_types_for_category(category: str) -> frozenset[str]:
    """event_type values (taxonomy class values) belonging to a filter group.

    Market shock events (``event_type='market_shock'``) belong to no world category.
    """
    return frozenset(cls.value for cls, group in CATEGORY_GROUP.items() if group == category)


_MAX_ID_ATTEMPTS = 5


def generate_event_id() -> str:
    return f"evt_{uuid.uuid4().hex[:12]}"


class EventService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = EventRepository(session)

    async def create(self, payload: EventCreate) -> CanonicalEvent:
        event, created = await self.create_if_absent(payload)
        if not created:
            raise ConflictError(f"Event '{event.id}' already exists")
        return event

    async def create_if_absent(self, payload: EventCreate) -> tuple[CanonicalEvent, bool]:
        """Insert the event unless its client id exists; returns ``(event, created)``.

        A duplicate returns the existing event with ``created=False`` and raises nothing.
        Payloads without an id always allocate a fresh one.
        """
        values = payload.model_dump(exclude={"id", "source_type", "metadata"})
        values["source_type"] = payload.source_type.value.upper()
        values["metadata_"] = payload.metadata
        client_id = payload.id

        try:
            event: CanonicalEvent | None = None
            attempts = 1 if client_id else _MAX_ID_ATTEMPTS
            for _ in range(attempts):
                values["id"] = client_id or generate_event_id()
                event = await self.repo.insert(values)
                if event is not None:
                    break
            if event is None:
                if not client_id:
                    await self.session.rollback()
                    raise DatabaseError("Could not allocate a unique event id")
                # Nothing was written; end the transaction, then load the existing row fresh.
                await self.session.commit()
                existing = await self.repo.get(client_id)
                if existing is None:  # deleted concurrently between insert and read
                    raise DatabaseError(f"Event '{client_id}' vanished during create")
                return existing, False
            await self.session.commit()
        except SQLAlchemyError:
            await self.session.rollback()
            raise

        logger.info(
            "event created",
            extra={"operation": "events.create", "event_id": event.id},
        )
        return event, True

    async def get(self, event_id: str) -> CanonicalEvent:
        event = await self.repo.get(event_id)
        if event is None:
            raise NotFoundError(f"Event '{event_id}' not found")
        return event

    async def list(
        self,
        limit: int,
        offset: int,
        source_type: SourceType | str | None = None,
        event_type: str | None = None,
        severity_min: float | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        category: str | None = None,
    ) -> tuple[list[CanonicalEvent], int]:
        source = SourceType(source_type).value if source_type is not None else None
        return await self.repo.list(
            limit=limit,
            offset=offset,
            source_type=source,
            event_type=event_type,
            severity_min=severity_min,
            start=start,
            end=end,
            event_types=event_types_for_category(category) if category is not None else None,
        )

    async def list_sources(self, event_id: str) -> Sequence[EventSource]:
        """Evidence rows for an event, oldest first; 404 when the event does not exist."""
        if not await self.repo.exists(event_id):
            raise NotFoundError(f"Event '{event_id}' not found")
        return await WorldRepository(self.session).list_sources(event_id)
