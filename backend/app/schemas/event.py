"""Canonical event schemas (Plan section 7).

The API represents ``source_type`` in lowercase; the database stores it uppercase.
"""

import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

EVENT_ID_PATTERN = r"^evt_[a-z0-9_]{1,64}$"
_EVENT_ID_RE = re.compile(EVENT_ID_PATTERN)

UnitInterval = Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)]
SignedUnit = Annotated[float, Field(ge=-1.0, le=1.0, allow_inf_nan=False)]
ShortText = Annotated[str, Field(min_length=1, max_length=200)]


class SourceType(StrEnum):
    WORLD = "world"
    MARKET = "market"
    FINANCIAL = "financial"

    @classmethod
    def _missing_(cls, value: object) -> "SourceType | None":
        # Accept the uppercase database representation as well.
        if isinstance(value, str):
            for member in cls:
                if member.value == value.lower():
                    return member
        return None


class EventCreate(BaseModel):
    """Payload for POST /events."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str | None = Field(
        default=None,
        pattern=EVENT_ID_PATTERN,
        description="Optional client id, evt_[a-z0-9_]{1,64}. Generated when omitted.",
    )
    timestamp: datetime = Field(description="Event time; must be timezone-aware.")
    source_type: SourceType
    event_type: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=300)
    summary: str | None = Field(default=None, max_length=5000)
    entities: list[ShortText] = Field(default_factory=list, max_length=200)
    companies: list[ShortText] = Field(default_factory=list, max_length=200)
    locations: list[ShortText] = Field(default_factory=list, max_length=200)
    economic_channels: dict[str, SignedUnit] = Field(default_factory=dict, max_length=100)
    severity: UnitInterval
    novelty: UnitInterval
    corroboration: UnitInterval = 0.0
    confidence: UnitInterval
    source_refs: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    metadata: dict[str, Any] = Field(default_factory=dict)
    is_mock: bool = False

    @field_validator("timestamp")
    @classmethod
    def _require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(
                "timestamp must be timezone-aware: include a UTC offset or 'Z', "
                "e.g. 2026-09-20T17:00:00Z"
            )
        return value.astimezone(UTC)


class Event(BaseModel):
    """Event as returned by the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    timestamp: datetime
    source_type: SourceType
    event_type: str
    title: str
    summary: str | None
    entities: list[str]
    companies: list[str]
    locations: list[str]
    economic_channels: dict[str, float]
    severity: float
    novelty: float
    corroboration: float
    confidence: float
    source_refs: list[dict[str, Any]]
    metadata: dict[str, Any] = Field(validation_alias="metadata_")
    is_mock: bool
    created_at: datetime
    ingested_at: datetime
    # Day 3 (additive): world-event evidence bookkeeping; defaults for pre-Day-3 rows.
    revision: int = 1
    updated_at: datetime | None = None
    source_count: int = 1
    independent_source_count: int = 1


class EventList(BaseModel):
    items: list[Event]
    total: int
    limit: int
    offset: int


def is_valid_event_id(value: str) -> bool:
    return bool(_EVENT_ID_RE.match(value))
