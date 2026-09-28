"""Stable domain contracts for Day 6 forecasting.

The primary target is cumulative abnormal return. These contracts deliberately keep
model status and diagnostics alongside predictions so an unavailable optional model
cannot be mistaken for a successful forecast.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

FORECAST_HORIZONS: dict[str, int] = {
    "1D": 1,
    "2D": 2,
    "5D": 5,
    "10D": 10,
    "20D": 20,
}


class ForecastAvailability(StrEnum):
    READY = "READY"
    FORECAST_UNAVAILABLE = "FORECAST_UNAVAILABLE"


class OODStatus(StrEnum):
    IN_DISTRIBUTION = "IN_DISTRIBUTION"
    OOD = "OOD"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ForecastHorizon:
    horizon: str
    trading_days: int
    target_timestamp: datetime | None
    q10: float | None
    q50: float | None
    q90: float | None
    probability_positive: float | None
    risk: float | None = None
    confidence: float | None = None
    score: float | None = None


@dataclass(frozen=True)
class ForecastResult:
    event_id: str
    symbol: str
    issued_at: datetime
    data_cutoff_at: datetime
    graph_snapshot_id: str | None
    model_version: str
    feature_version: str
    feature_hash: str
    horizons: dict[str, ForecastHorizon]
    recommended_horizon: str | None
    information_half_life: float | None
    model_status: ForecastAvailability
    diagnostics: dict[str, Any] = field(default_factory=dict)
    unavailable_reason: str | None = None

    @staticmethod
    def hash_features(features: dict[str, float | None]) -> str:
        payload = json.dumps(features, sort_keys=True, separators=(",", ":"), allow_nan=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class DatasetRow:
    """One event-company training example with targets computed separately."""

    event_id: str
    symbol: str
    event_group: str
    issuance_timestamp: datetime
    data_cutoff_at: datetime
    graph_snapshot_id: str | None
    feature_version: str
    features: dict[str, float | None]
    targets: dict[str, float]


@dataclass(frozen=True)
class DatasetSplit:
    train: tuple[DatasetRow, ...]
    validation: tuple[DatasetRow, ...]
    test: tuple[DatasetRow, ...]
    diagnostics: dict[str, Any]
