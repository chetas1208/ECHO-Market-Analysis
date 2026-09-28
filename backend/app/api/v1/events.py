from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Query, status
from fastapi.exceptions import RequestValidationError
from pydantic import AfterValidator

from app.api.deps import EventServiceDep
from app.schemas.common import ErrorResponse
from app.schemas.event import Event, EventCreate, EventList, SourceType
from app.schemas.world import EventSourceOut, EventSourcesResponse

router = APIRouter(prefix="/events", tags=["events"])

_ERRORS = {
    404: {"model": ErrorResponse, "description": "Not found"},
    409: {"model": ErrorResponse, "description": "Conflict"},
    422: {"model": ErrorResponse, "description": "Validation error"},
}


EventCategory = Literal["geopolitics", "energy", "supply_chain", "technology", "macro", "other"]


def _require_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("must be timezone-aware: include a UTC offset or 'Z'")
    return value.astimezone(UTC)


AwareDatetime = Annotated[datetime, AfterValidator(_require_aware)]


@router.post(
    "",
    response_model=Event,
    status_code=status.HTTP_201_CREATED,
    responses={409: _ERRORS[409], 422: _ERRORS[422]},
)
async def create_event(payload: EventCreate, service: EventServiceDep) -> Event:
    event = await service.create(payload)
    return Event.model_validate(event)


@router.get("", response_model=EventList, responses={422: _ERRORS[422]})
async def list_events(
    service: EventServiceDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    source_type: Annotated[
        SourceType | None,
        Query(description="Filter by source type (world|market|financial), case-insensitive."),
    ] = None,
    event_type: Annotated[
        str | None,
        Query(min_length=1, max_length=100, description="Filter by exact event_type."),
    ] = None,
    severity_min: Annotated[
        float | None,
        Query(ge=0.0, le=1.0, allow_inf_nan=False, description="Minimum severity, inclusive."),
    ] = None,
    start: Annotated[
        AwareDatetime | None, Query(description="Earliest event timestamp, inclusive (aware ISO).")
    ] = None,
    end: Annotated[
        AwareDatetime | None, Query(description="Latest event timestamp, inclusive (aware ISO).")
    ] = None,
    category: Annotated[
        EventCategory | None,
        Query(
            description="World category filter. Market shock events belong to no category "
            "and are excluded when this is set."
        ),
    ] = None,
) -> EventList:
    if start is not None and end is not None and start > end:
        raise RequestValidationError(
            [{"type": "value_error", "loc": ("query", "start"), "msg": "start must be <= end"}]
        )
    items, total = await service.list(
        limit=limit,
        offset=offset,
        source_type=source_type,
        event_type=event_type,
        severity_min=severity_min,
        start=start,
        end=end,
        category=category,
    )
    return EventList(
        items=[Event.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{event_id}/sources",
    response_model=EventSourcesResponse,
    responses={404: _ERRORS[404]},
)
async def list_event_sources(event_id: str, service: EventServiceDep) -> EventSourcesResponse:
    rows = await service.list_sources(event_id)
    return EventSourcesResponse(
        items=[EventSourceOut.model_validate(row) for row in rows], total=len(rows)
    )


@router.get(
    "/{event_id}",
    response_model=Event,
    responses={404: _ERRORS[404]},
)
async def get_event(event_id: str, service: EventServiceDep) -> Event:
    return Event.model_validate(await service.get(event_id))
