from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.services.events import EventService
from app.services.health import HealthService

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_event_service(session: SessionDep) -> EventService:
    return EventService(session)


def get_health_service(session: SessionDep) -> HealthService:
    return HealthService(session)


EventServiceDep = Annotated[EventService, Depends(get_event_service)]
HealthServiceDep = Annotated[HealthService, Depends(get_health_service)]
