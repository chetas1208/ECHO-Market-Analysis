"""ECHO-owned market data types. Provider SDK objects never cross this boundary.

All timestamps are timezone-aware UTC. A Bar's ``timestamp`` is the bar START time.
Providers emit CLOSED 1m bars only; 5m/15m are aggregated locally (aggregation.py).
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Interval(StrEnum):
    M1 = "1m"
    M5 = "5m"
    M15 = "15m"

    @property
    def minutes(self) -> int:
        return {"1m": 1, "5m": 5, "15m": 15}[self.value]


class ProviderName(StrEnum):
    MASSIVE = "massive"
    ALPACA = "alpaca"
    REPLAY = "replay"


class ProviderState(StrEnum):
    UNCONFIGURED = "UNCONFIGURED"
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    DEGRADED = "DEGRADED"
    RECONNECTING = "RECONNECTING"
    STALE = "STALE"


class DataMode(StrEnum):
    """What the UI must show. Replay/mock must NEVER masquerade as LIVE."""

    LIVE = "LIVE"
    REPLAY = "REPLAY"
    MOCK = "MOCK"
    OFFLINE = "OFFLINE"


class FeatureStatus(StrEnum):
    READY = "READY"
    WARMING_UP = "WARMING_UP"
    UNAVAILABLE = "UNAVAILABLE"


class ShockDirection(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"


class ShockLevel(StrEnum):
    NONE = "none"
    WATCH = "watch"
    SHOCK = "shock"
    SEVERE = "severe"


class Bar(BaseModel):
    """Normalized market observation (one OHLCV bar)."""

    model_config = ConfigDict(frozen=True)

    symbol: str
    timestamp: datetime  # bar start, UTC
    interval: Interval = Interval.M1
    open: float
    high: float
    low: float
    close: float
    volume: float = Field(ge=0)
    vwap: float | None = None
    trade_count: int | None = Field(default=None, ge=0)
    source: ProviderName
    received_at: datetime | None = None

    @field_validator("symbol")
    @classmethod
    def _upper(cls, v: str) -> str:
        v = v.strip().upper()
        if not v:
            raise ValueError("symbol must be non-empty")
        return v

    @field_validator("timestamp", "received_at")
    @classmethod
    def _aware_utc(cls, v: datetime | None) -> datetime | None:
        if v is None:
            return v
        if v.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        return v.astimezone(UTC)

    @model_validator(mode="after")
    def _ohlc(self) -> Bar:
        if self.high < max(self.open, self.close, self.low) or self.low > min(
            self.open, self.close, self.high
        ):
            raise ValueError("inconsistent OHLC")
        if min(self.open, self.high, self.low, self.close) <= 0:
            raise ValueError("prices must be > 0")
        return self

    @property
    def key(self) -> tuple[str, datetime, str, str]:
        """Identity used for dedupe/upsert: (symbol, timestamp, interval, source)."""
        return (self.symbol, self.timestamp, self.interval.value, self.source.value)


class ProviderHealth(BaseModel):
    provider: ProviderName
    state: ProviderState
    configured: bool
    mode: DataMode
    last_message_at: datetime | None = None
    last_error: str | None = None
    reconnect_attempts: int = 0
    subscribed_symbols: list[str] = Field(default_factory=list)
    messages_received: int = 0
    malformed_messages: int = 0


class FeatureValue(BaseModel):
    value: float | None = None
    status: FeatureStatus = FeatureStatus.UNAVAILABLE


class SymbolFeatures(BaseModel):
    """Feature snapshot for one symbol as of a CLOSED 1m bar (no lookahead)."""

    symbol: str
    as_of: datetime  # start ts of the last closed 1m bar used
    price: float | None = None
    ret_1m: FeatureValue = Field(default_factory=FeatureValue)  # log returns
    ret_5m: FeatureValue = Field(default_factory=FeatureValue)
    ret_15m: FeatureValue = Field(default_factory=FeatureValue)
    return_z: FeatureValue = Field(default_factory=FeatureValue)  # z of ret_5m
    volume_z: FeatureValue = Field(default_factory=FeatureValue)
    volume_z_method: str | None = None  # "tod" | "rolling"
    volatility_z: FeatureValue = Field(default_factory=FeatureValue)
    beta_market: FeatureValue = Field(default_factory=FeatureValue)
    beta_sector: FeatureValue = Field(default_factory=FeatureValue)
    market_residual: FeatureValue = Field(default_factory=FeatureValue)  # 5m, log-return units
    market_residual_z: FeatureValue = Field(default_factory=FeatureValue)
    sector_residual: FeatureValue = Field(default_factory=FeatureValue)
    sector_residual_z: FeatureValue = Field(default_factory=FeatureValue)
    sector_benchmark: str | None = None
    market_benchmark: str | None = None
    overall_status: FeatureStatus = FeatureStatus.UNAVAILABLE  # READY only if all required READY


class ShockAssessment(BaseModel):
    """Heuristic score. NOT a calibrated probability (decisions D-023 / Day 2 Rule 7)."""

    symbol: str
    as_of: datetime
    score: float = Field(ge=0, le=1)
    level: ShockLevel
    direction: ShockDirection | None = None
    components: dict[str, float] = Field(default_factory=dict)  # contribution per signal
    ready: bool = False
    calibrated: bool = False
