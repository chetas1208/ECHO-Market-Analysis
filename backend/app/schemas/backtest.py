"""Registered historical replay API contracts."""

from typing import Literal

from pydantic import BaseModel


class BacktestCreateIn(BaseModel):
    dataset: Literal["fixture_validation"] = "fixture_validation"
    strategy_version: Literal["echo-rp-v1"] = "echo-rp-v1"
    split: Literal["TRAIN", "VALIDATION", "TEST"] = "TEST"
    write_artifacts: bool = True


class BacktestRunOut(BaseModel):
    run_id: str
    strategy_version: str
    config_hash: str
    dataset_hash: str
    split: str
    mode: Literal["HISTORICAL_REPLAY"]
    metrics: dict[str, object]
    artifact_path: str | None = None


class BacktestListOut(BaseModel):
    items: list[BacktestRunOut]
    total: int


class BacktestTradeOut(BaseModel):
    case_key: str
    event_id: str
    event_class: str
    symbol: str
    sector: str
    side: str
    signal_timestamp: str
    entry_timestamp: str | None
    exit_timestamp: str | None
    horizon: str
    forecast_q50: float | None
    probability_positive: float | None
    graph_exposure: float | None
    cause_score: float | None
    absorption_ratio: float | None
    decision_reasons: list[str]
    entry_price: float | None
    exit_price: float | None
    costs: float
    gross_pnl: float
    net_pnl: float
    status: str
    exit_reason: str | None
    notional: float
