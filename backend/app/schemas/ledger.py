"""Day 7 prediction ledger and simulator API contracts."""

from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, Field, model_validator

from app.schemas.forecast import ForecastPreviewOut


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("must be timezone-aware: include a UTC offset or 'Z'")
    return value.astimezone(UTC)


AwareDatetime = Annotated[datetime, AfterValidator(_aware_utc)]
Horizon = Literal["1D", "2D", "5D", "10D", "20D"]


class ForecastVintageCreateIn(BaseModel):
    preview: ForecastPreviewOut
    config_hash: str = Field(min_length=16, max_length=128)
    forecasting_engine_version: str = Field(default="echo-ledger-v1", min_length=1, max_length=100)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=200)


class ForecastPointOut(BaseModel):
    horizon: Horizon
    horizon_trading_days: int
    target_timestamp: datetime
    q10: float
    q50: float
    q90: float
    probability_positive: float
    expected_abnormal_return: float | None
    forecast_risk: float | None


class ForecastVintageOut(BaseModel):
    id: UUID
    event_id: str | None
    symbol: str
    issued_at: datetime
    data_cutoff_at: datetime
    created_at: datetime
    graph_snapshot_id: str | None
    event_snapshot_id: str | None
    event_snapshot: dict[str, Any] | None
    model_version: str
    feature_version: str
    model_artifact_hash: str | None
    feature_hash: str | None
    feature_snapshot: dict[str, Any]
    config_hash: str | None
    forecasting_engine_version: str
    recommended_horizon: str | None
    information_half_life: float | None
    ood_status: str | None
    abstention_state: str | None
    content_hash: str | None
    request_hash: str | None
    horizons: list[ForecastPointOut]


class ForecastVintageListOut(BaseModel):
    items: list[ForecastVintageOut]
    total: int
    limit: int
    offset: int


class ForecastActualCreateIn(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    horizon: Literal["INTRADAY", "1D", "2D", "5D", "10D", "20D"]
    observed_at: AwareDatetime
    market_timestamp: AwareDatetime
    actual_price: float | None = Field(default=None, gt=0)
    actual_return: float | None = None
    actual_abnormal_return: float | None = None
    market_return: float | None = None
    sector_return: float | None = None
    source: str = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def _has_measurement(self) -> "ForecastActualCreateIn":
        if (
            self.actual_abnormal_return is None
            and self.actual_price is None
            and self.actual_return is None
        ):
            raise ValueError("an actual price, return, or abnormal return is required")
        return self


class ForecastActualOut(ForecastActualCreateIn):
    id: UUID
    forecast_run_id: UUID
    observation_hash: str
    created_at: datetime


class ForecastEvaluationOut(BaseModel):
    forecast_run_id: str
    horizon: Horizon
    status: Literal["PENDING", "PARTIAL", "COMPLETE", "UNAVAILABLE"]
    evaluated_at: datetime
    predicted_q10: float | None
    predicted_q50: float | None
    predicted_q90: float | None
    probability_positive: float | None
    actual_abnormal_return: float | None
    absolute_error: float | None
    squared_error: float | None
    directional_correct: bool | None
    interval_covered: bool | None
    pinball_q10: float | None
    pinball_q50: float | None
    pinball_q90: float | None
    brier_contribution: float | None


class ForecastEvaluationListOut(BaseModel):
    items: list[ForecastEvaluationOut]


class SimulationCreateIn(BaseModel):
    horizon: Horizon | None = None
    mode: Literal["HISTORICAL_REPLAY", "LIVE_SIMULATION"] = "HISTORICAL_REPLAY"
    initial_equity: float = Field(default=100_000, gt=0)
    risk_budget: float = Field(default=1_000, gt=0)
    min_q50_abs: float = Field(default=0.005, ge=0)
    probability_threshold: float = Field(default=0.55, ge=0, le=1)
    max_interval_width: float = Field(default=0.25, gt=0)
    max_position_pct: float = Field(default=0.20, gt=0, le=1)
    commission_bps: float = Field(default=0, ge=0)
    spread_bps: float = Field(default=5, ge=0)
    slippage_bps: float = Field(default=5, ge=0)
    stop_multiple: float = Field(default=2, gt=0)
    hedge_symbol: str | None = Field(default=None, min_length=1, max_length=32)
    hedge_ratio: float = Field(default=0, ge=0, le=1)
    strategy_version: str = Field(default="echo-sim-v1", min_length=1, max_length=100)


class SimulatedTradeOut(BaseModel):
    id: UUID
    forecast_run_id: UUID
    created_at: datetime
    symbol: str
    side: Literal["LONG", "SHORT", "NO_TRADE"]
    decision_timestamp: datetime
    entry_timestamp: datetime | None
    entry_price: float | None
    planned_exit_horizon: Horizon
    planned_exit_timestamp: datetime
    position_size: float
    notional: float
    hedge_symbol: str | None
    hedge_ratio: float
    stop_type: str | None
    stop_value: float | None
    strategy_version: str
    config_hash: str
    status: str
    gross_pnl: float
    costs: float
    hedge_pnl: float
    net_pnl: float
    return_on_allocated_capital: float | None
    plan_hash: str
    reason: str | None
    exit_timestamp: datetime | None = None
    exit_price: float | None = None


class IntegrityOut(BaseModel):
    forecast_id: UUID
    status: Literal["VALID", "CORRUPT"]
    stored_content_hash: str | None
    computed_content_hash: str
    model_version: str
    model_artifact_hash: str | None
    feature_hash: str | None
    graph_snapshot_id: str | None


class PortfolioOut(BaseModel):
    initial_equity: float
    cash: float
    gross_exposure: float
    net_exposure: float
    equity: float
    realized_pnl: float
    unrealized_pnl: float
    trade_count: int
