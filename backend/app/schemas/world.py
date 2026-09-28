"""Day 3 world API schemas: event evidence and world feed status."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.world.types import WorldMode, WorldProviderHealth

TextAnalyzerStatus = Literal["AVAILABLE", "LOADING", "UNAVAILABLE", "DISABLED"]


class EventSourceOut(BaseModel):
    """Public view of one evidence row. Never exposes content hashes or raw payloads."""

    model_config = ConfigDict(from_attributes=True)

    provider: str
    source_name: str
    source_group: str | None
    source_url: str | None
    headline: str | None
    published_at: datetime | None
    retrieved_at: datetime
    is_independent: bool
    syndicated_from: str | None
    reliability: float | None


class EventSourcesResponse(BaseModel):
    items: list[EventSourceOut]
    total: int


class WorldStatus(BaseModel):
    mode: WorldMode
    provider: WorldProviderHealth
    counters: dict[str, int | float | str | datetime | None]
    text_analyzer: TextAnalyzerStatus
