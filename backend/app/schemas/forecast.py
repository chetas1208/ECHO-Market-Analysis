"""Forecast preview and model-status API contracts."""

from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, Field


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("must be timezone-aware: include a UTC offset or 'Z'")
    return value.astimezone(UTC)


AwareDatetime = Annotated[datetime, AfterValidator(_aware_utc)]


class ForecastPreviewIn(BaseModel):
    event_id: str
    symbol: str
    graph_snapshot_id: str | None = None
    data_cutoff_at: AwareDatetime | None = None


class ForecastHorizonOut(BaseModel):
    horizon: Literal["1D", "2D", "5D", "10D", "20D"]
    trading_days: int = Field(ge=1)
    target_timestamp: datetime | None
    q10: float | None
    q50: float | None
    q90: float | None
    probability_positive: float | None = Field(default=None, ge=0, le=1)
    risk: float | None = Field(default=None, ge=0)
    confidence: float | None = Field(default=None, ge=0, le=1)
    score: float | None


class ForecastPreviewOut(BaseModel):
    event_id: str
    symbol: str
    issued_at: datetime
    data_cutoff_at: datetime
    graph_snapshot_id: str | None
    model_version: str
    feature_version: str
    feature_hash: str
    model_artifact_hash: str | None = None
    horizons: dict[str, ForecastHorizonOut]
    recommended_horizon: str | None
    information_half_life: float | None
    model_status: str
    unavailable_reason: str | None = None
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class ForecastingStatusOut(BaseModel):
    artifact_available: bool
    model_status: str
    model_version: str | None
    feature_version: str | None
    training_cutoff: datetime | None
    artifact_hash: str | None
    backend: str | None
    chronos_status: str
    chronos_model: str
    artifact_path: str
