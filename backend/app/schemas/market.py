"""Response models for the /market API (Day 2 contract). All timestamps are ISO-8601 UTC ('Z')."""

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.market.types import (
    DataMode,
    ProviderHealth,
    ProviderName,
    ShockAssessment,
    SymbolFeatures,
)
from app.schemas.event import Event


def _to_utc(value: datetime) -> datetime:
    """Normalise to aware UTC (naive values are assumed to already be UTC)."""
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


UtcDatetime = Annotated[datetime, AfterValidator(_to_utc)]

SymbolState = Literal["NORMAL", "WATCH", "SHOCK", "SEVERE", "WARMING_UP", "NO_DATA"]


class QueueStats(BaseModel):
    depth: int = 0
    capacity: int = 0
    dropped: int = 0


class MarketStatus(BaseModel):
    mode: DataMode
    providers: list[ProviderHealth] = Field(default_factory=list)
    active_provider: ProviderName | None = None
    subscribed_symbols: list[str] = Field(default_factory=list)
    last_observation_at: UtcDatetime | None = None
    queue: QueueStats = Field(default_factory=QueueStats)
    replay_finished: bool = False
    session: str = "CLOSED"


class SymbolRow(BaseModel):
    symbol: str
    group: str
    role: Literal["equity", "benchmark"]
    sector_benchmark: str | None = None
    price: float | None = None
    change_pct: float | None = None
    as_of: UtcDatetime | None = None
    state: SymbolState = "NO_DATA"
    shock_score: float | None = None
    volume_z: float | None = None
    return_5m: float | None = None
    sector_residual: float | None = None
    direction: Literal["positive", "negative"] | None = None


class SymbolsResponse(BaseModel):
    items: list[SymbolRow]


class BarOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    timestamp: UtcDatetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    source: ProviderName


class BarsResponse(BaseModel):
    symbol: str
    interval: str
    items: list[BarOut]


class FeaturesResponse(SymbolFeatures):
    """SymbolFeatures plus the shock assessment. ``as_of`` is null when nothing computed yet."""

    as_of: UtcDatetime | None = None  # type: ignore[assignment]
    assessment: ShockAssessment | None = None


class ShocksResponse(BaseModel):
    items: list[Event]
