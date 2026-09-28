"""Registered, deterministic historical replay endpoints."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from app.backtesting.artifacts import write_artifacts
from app.backtesting.datasets import fixture_cases
from app.backtesting.engine import BacktestEngine, BacktestResult
from app.backtesting.research import report_dict, run_research
from app.schemas.backtest import BacktestCreateIn, BacktestListOut, BacktestRunOut, BacktestTradeOut
from app.strategy.policy import StrategyConfig

router = APIRouter(prefix="/backtests", tags=["backtesting"])
_ROOT = Path(__file__).resolve().parents[4] / "artifacts" / "backtests"
_RUNS: dict[str, BacktestResult] = {}


def _out(result: BacktestResult, artifact_path: Path | None = None) -> BacktestRunOut:
    return BacktestRunOut(
        run_id=result.run_id,
        strategy_version=result.strategy_version,
        config_hash=result.config_hash,
        dataset_hash=result.dataset_hash,
        split=result.split,
        mode="HISTORICAL_REPLAY",
        metrics=result.metrics.as_dict(),
        artifact_path=str(artifact_path) if artifact_path else None,
    )


@router.post("", response_model=BacktestRunOut, status_code=201)
async def create_backtest(payload: BacktestCreateIn) -> BacktestRunOut:
    cases = fixture_cases()
    result = BacktestEngine(StrategyConfig(strategy_version=payload.strategy_version)).run(
        cases, split=payload.split
    )
    artifact_path = None
    if payload.write_artifacts:
        try:
            artifact_path = write_artifacts(result, _ROOT)
        except FileExistsError:
            artifact_path = _ROOT / result.run_id
    _RUNS[result.run_id] = result
    return _out(result, artifact_path)


@router.get("", response_model=BacktestListOut)
async def list_backtests() -> BacktestListOut:
    items = [
        _out(result, _ROOT / result.run_id if (_ROOT / result.run_id).exists() else None)
        for result in _RUNS.values()
    ]
    return BacktestListOut(items=items, total=len(items))


@router.get("/research")
async def backtest_research() -> dict[str, Any]:
    return report_dict(run_research(fixture_cases(), StrategyConfig()))


@router.get("/{run_id}", response_model=BacktestRunOut)
async def get_backtest(run_id: str) -> BacktestRunOut:
    result = _RUNS.get(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="backtest run not found")
    return _out(result, _ROOT / result.run_id if (_ROOT / result.run_id).exists() else None)


@router.get("/{run_id}/trades", response_model=list[BacktestTradeOut])
async def get_backtest_trades(run_id: str) -> list[BacktestTradeOut]:
    result = _RUNS.get(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="backtest run not found")
    return [
        BacktestTradeOut(**{**trade.as_dict(), "decision_reasons": list(trade.decision_reasons)})
        for trade in result.trades
    ]
