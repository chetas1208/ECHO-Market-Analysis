"""Day 7 immutable forecast ledger and deterministic paper simulation API."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from app.api.deps import SessionDep
from app.core.errors import NotFoundError
from app.models import CanonicalEvent, ForecastActual, ForecastPoint, ForecastRun, SimulatedTrade
from app.schemas.ledger import (
    ForecastActualCreateIn,
    ForecastActualOut,
    ForecastEvaluationListOut,
    ForecastPointOut,
    ForecastVintageCreateIn,
    ForecastVintageListOut,
    ForecastVintageOut,
    IntegrityOut,
    PortfolioOut,
    SimulatedTradeOut,
    SimulationCreateIn,
)
from app.services.prediction_ledger import PredictionLedgerService
from app.services.trade_simulator import TradeSimulationService

router = APIRouter(tags=["prediction-ledger"])


def _vintage_out(run: ForecastRun, points: list[ForecastPoint]) -> ForecastVintageOut:
    return ForecastVintageOut(
        id=run.id,
        event_id=run.event_id,
        symbol=run.symbol,
        issued_at=run.prediction_timestamp,
        data_cutoff_at=run.data_cutoff_at,
        created_at=run.created_at,
        graph_snapshot_id=run.graph_snapshot_id,
        event_snapshot_id=run.event_snapshot_id,
        event_snapshot=run.event_snapshot,
        model_version=run.model_version,
        feature_version=run.feature_version,
        model_artifact_hash=run.model_artifact_hash,
        feature_hash=run.feature_hash,
        feature_snapshot=run.feature_snapshot,
        config_hash=run.config_hash,
        forecasting_engine_version=run.forecasting_engine_version,
        recommended_horizon=run.recommended_horizon,
        information_half_life=run.information_half_life,
        ood_status=run.ood_status,
        abstention_state=run.abstention_state,
        content_hash=run.content_hash,
        request_hash=run.request_hash,
        horizons=[
            ForecastPointOut(
                horizon=point.horizon,
                horizon_trading_days=point.horizon_trading_days,
                target_timestamp=point.target_timestamp,
                q10=point.q10,
                q50=point.q50,
                q90=point.q90,
                probability_positive=point.probability_positive,
                expected_abnormal_return=point.expected_abnormal_return,
                forecast_risk=point.forecast_risk,
            )
            for point in points
        ],
    )


def _actual_out(actual: ForecastActual) -> ForecastActualOut:
    return ForecastActualOut(
        id=actual.id,
        forecast_run_id=actual.forecast_run_id,
        symbol=actual.symbol,
        horizon=actual.horizon,
        observed_at=actual.observed_at,
        market_timestamp=actual.market_timestamp,
        actual_price=actual.actual_price,
        actual_return=actual.actual_return,
        actual_abnormal_return=actual.actual_abnormal_return,
        market_return=actual.market_return,
        sector_return=actual.sector_return,
        source=actual.source,
        observation_hash=actual.observation_hash,
        created_at=actual.created_at,
    )


def _trade_out(trade: SimulatedTrade) -> SimulatedTradeOut:
    metadata = trade.metadata_ or {}
    return SimulatedTradeOut(
        id=trade.id,
        forecast_run_id=trade.forecast_run_id,
        created_at=trade.created_at,
        symbol=trade.symbol,
        side=trade.side,
        decision_timestamp=trade.decision_timestamp,
        entry_timestamp=trade.entry_timestamp,
        entry_price=trade.entry_price,
        planned_exit_horizon=trade.planned_exit_horizon,
        planned_exit_timestamp=trade.planned_exit_timestamp,
        position_size=trade.position_size,
        notional=trade.notional,
        hedge_symbol=trade.hedge_symbol,
        hedge_ratio=trade.hedge_ratio,
        stop_type=trade.stop_type,
        stop_value=trade.stop_value,
        strategy_version=trade.strategy_version,
        config_hash=trade.config_hash,
        status=trade.status,
        gross_pnl=trade.gross_pnl,
        costs=trade.costs,
        hedge_pnl=trade.hedge_pnl,
        net_pnl=trade.net_pnl,
        return_on_allocated_capital=trade.return_on_allocated_capital,
        plan_hash=trade.plan_hash,
        reason=metadata.get("reason"),
    )


@router.post("/forecasts", response_model=ForecastVintageOut, status_code=201)
async def create_forecast_vintage(
    payload: ForecastVintageCreateIn, session: SessionDep
) -> ForecastVintageOut:
    event = await session.get(CanonicalEvent, payload.preview.event_id)
    if event is None:
        raise NotFoundError(f"Event '{payload.preview.event_id}' not found")
    service = PredictionLedgerService(session)
    run = await service.create_vintage(
        payload.preview,
        event,
        config_hash=payload.config_hash,
        forecasting_engine_version=payload.forecasting_engine_version,
        idempotency_key=payload.idempotency_key,
    )
    loaded, points = await service.get_vintage(run.id)
    return _vintage_out(loaded, points)


@router.get("/forecasts", response_model=ForecastVintageListOut)
async def list_forecast_vintages(
    session: SessionDep,
    symbol: Annotated[str | None, Query(min_length=1, max_length=32)] = None,
    event_id: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ForecastVintageListOut:
    service = PredictionLedgerService(session)
    runs, total = await service.list_vintages(
        symbol=symbol, event_id=event_id, limit=limit, offset=offset
    )
    items = []
    for run in runs:
        loaded, points = await service.get_vintage(run.id)
        items.append(_vintage_out(loaded, points))
    return ForecastVintageListOut(items=items, total=total, limit=limit, offset=offset)


@router.get("/forecasts/{forecast_id}", response_model=ForecastVintageOut)
async def get_forecast_vintage(forecast_id: uuid.UUID, session: SessionDep) -> ForecastVintageOut:
    service = PredictionLedgerService(session)
    run, points = await service.get_vintage(forecast_id)
    return _vintage_out(run, points)


@router.post("/forecasts/{forecast_id}/actuals", response_model=ForecastActualOut, status_code=201)
async def append_forecast_actual(
    forecast_id: uuid.UUID, payload: ForecastActualCreateIn, session: SessionDep
) -> ForecastActualOut:
    actual = await PredictionLedgerService(session).append_actual(forecast_id, payload.model_dump())
    return _actual_out(actual)


@router.get("/forecasts/{forecast_id}/actuals", response_model=list[ForecastActualOut])
async def list_forecast_actuals(
    forecast_id: uuid.UUID, session: SessionDep
) -> list[ForecastActualOut]:
    actuals = await PredictionLedgerService(session).list_actuals(forecast_id)
    return [_actual_out(item) for item in actuals]


@router.get("/forecasts/{forecast_id}/evaluation", response_model=ForecastEvaluationListOut)
async def evaluate_forecast(
    forecast_id: uuid.UUID, session: SessionDep
) -> ForecastEvaluationListOut:
    items = await PredictionLedgerService(session).evaluate(forecast_id)
    return ForecastEvaluationListOut(items=items)


@router.get("/forecasts/{forecast_id}/integrity", response_model=IntegrityOut)
async def verify_forecast_integrity(forecast_id: uuid.UUID, session: SessionDep) -> IntegrityOut:
    return IntegrityOut(**(await PredictionLedgerService(session).verify_integrity(forecast_id)))


@router.get("/forecasts/{forecast_id}/export")
async def export_forecast(forecast_id: uuid.UUID, session: SessionDep) -> JSONResponse:
    return JSONResponse(content=await PredictionLedgerService(session).export(forecast_id))


@router.post("/forecasts/{forecast_id}/simulate", response_model=SimulatedTradeOut, status_code=201)
async def simulate_forecast(
    forecast_id: uuid.UUID, payload: SimulationCreateIn, session: SessionDep
) -> SimulatedTradeOut:
    trade = await TradeSimulationService(session).create(forecast_id, payload)
    return _trade_out(trade)


@router.get("/simulations/{simulation_id}", response_model=SimulatedTradeOut)
async def get_simulation(simulation_id: uuid.UUID, session: SessionDep) -> SimulatedTradeOut:
    return _trade_out(await TradeSimulationService(session).get(simulation_id))


@router.get("/portfolio/simulated", response_model=PortfolioOut)
async def get_simulated_portfolio(session: SessionDep) -> PortfolioOut:
    return PortfolioOut(**(await TradeSimulationService(session).portfolio()))
