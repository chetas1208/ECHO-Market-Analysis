"""Ephemeral Day 6 forecast preview and model-status endpoints.

These routes never insert into ``forecast_runs`` or ``forecast_points``. Day 7 owns
permanent forecast-vintage creation.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path

from fastapi import APIRouter

from app.api.deps import SessionDep
from app.core.config import get_settings
from app.core.errors import NotFoundError
from app.forecasting.chronos import Chronos2SmallBaseline
from app.forecasting.engine import ForecastArtifactBundle, generate_forecast
from app.forecasting.features import FeatureLeakageError, build_feature_vector
from app.forecasting.types import FORECAST_HORIZONS, ForecastAvailability, ForecastResult
from app.forecasting.volatility import HARVolatilityModel
from app.graph.service import ShockGraphService
from app.market.calendar import NY, MarketCalendar
from app.market.types import Interval
from app.market.universe import get_universe
from app.repositories.events import EventRepository
from app.repositories.market import MarketBarRepository
from app.schemas.forecast import ForecastingStatusOut, ForecastPreviewIn, ForecastPreviewOut

router = APIRouter(tags=["forecasting"])


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _result_out(result: ForecastResult) -> ForecastPreviewOut:
    return ForecastPreviewOut(
        event_id=result.event_id,
        symbol=result.symbol,
        issued_at=result.issued_at,
        data_cutoff_at=result.data_cutoff_at,
        graph_snapshot_id=result.graph_snapshot_id,
        model_version=result.model_version,
        feature_version=result.feature_version,
        feature_hash=result.feature_hash,
        model_artifact_hash=result.diagnostics.get("artifact_hash"),
        horizons={name: value.__dict__ for name, value in result.horizons.items()},
        recommended_horizon=result.recommended_horizon,
        information_half_life=result.information_half_life,
        model_status=result.model_status.value,
        unavailable_reason=result.unavailable_reason,
        diagnostics=result.diagnostics,
    )


def _unavailable(
    *,
    event_id: str,
    symbol: str,
    issued_at: datetime,
    cutoff: datetime,
    reason: str,
    snapshot_id: str | None = None,
) -> ForecastPreviewOut:
    return _result_out(
        ForecastResult(
            event_id=event_id,
            symbol=symbol,
            issued_at=issued_at,
            data_cutoff_at=cutoff,
            graph_snapshot_id=snapshot_id,
            model_version="unavailable",
            feature_version="echo-features-v1",
            feature_hash=ForecastResult.hash_features({}),
            horizons={},
            recommended_horizon=None,
            information_half_life=None,
            model_status=ForecastAvailability.FORECAST_UNAVAILABLE,
            diagnostics={},
            unavailable_reason=reason,
        )
    )


def _future_timestamps(cutoff: datetime) -> dict[str, datetime]:
    calendar = MarketCalendar()
    # Session selection is based on New York dates, not UTC dates around midnight.
    local_date = _utc(cutoff).astimezone(NY).date()
    sessions: list[datetime] = []
    candidate = local_date + timedelta(days=1)
    while len(sessions) < max(FORECAST_HORIZONS.values()):
        bounds = calendar.session_bounds(candidate)
        if bounds is not None:
            sessions.append(bounds[1])
        candidate += timedelta(days=1)
    return {horizon: sessions[days - 1] for horizon, days in FORECAST_HORIZONS.items()}


def _artifact_path() -> Path:
    return get_settings().forecast_artifact_path


@router.get("/forecasting/status", response_model=ForecastingStatusOut)
async def forecasting_status() -> ForecastingStatusOut:
    path = _artifact_path()
    artifact: ForecastArtifactBundle | None = None
    if path.exists():
        try:
            artifact = ForecastArtifactBundle.load(path)
        except Exception:
            artifact = None
    chronos = Chronos2SmallBaseline()
    chronos_status = chronos.status()
    return ForecastingStatusOut(
        artifact_available=artifact is not None,
        model_status="READY" if artifact is not None else "FORECAST_UNAVAILABLE",
        model_version=artifact.model_version if artifact else None,
        feature_version=artifact.feature_version if artifact else None,
        training_cutoff=artifact.training_cutoff if artifact else None,
        artifact_hash=artifact.artifact_hash if artifact else None,
        backend=artifact.backend if artifact else None,
        chronos_status=chronos_status,
        chronos_model=chronos.model_id,
        artifact_path=str(path),
    )


@router.post("/forecasts/preview", response_model=ForecastPreviewOut)
async def forecast_preview(payload: ForecastPreviewIn, session: SessionDep) -> ForecastPreviewOut:
    events = EventRepository(session)
    event = await events.get(payload.event_id)
    if event is None:
        raise NotFoundError(f"Event '{payload.event_id}' not found")
    symbol = payload.symbol.strip().upper()
    cutoff = _utc(payload.data_cutoff_at or event.ingested_at)
    issued_at = cutoff
    artifact_path = _artifact_path()
    if not artifact_path.exists():
        return _unavailable(
            event_id=event.id,
            symbol=symbol,
            issued_at=issued_at,
            cutoff=cutoff,
            reason="model_artifact_unavailable",
        )
    try:
        artifact = ForecastArtifactBundle.load(artifact_path)
    except Exception as exc:
        return _unavailable(
            event_id=event.id,
            symbol=symbol,
            issued_at=issued_at,
            cutoff=cutoff,
            reason=f"model_artifact_invalid:{type(exc).__name__}",
        )

    graph = ShockGraphService(session)
    try:
        if payload.graph_snapshot_id:
            snapshot, _, _ = await graph.load_snapshot(payload.graph_snapshot_id)
            if _utc(snapshot.created_at) > cutoff:
                return _unavailable(
                    event_id=event.id,
                    symbol=symbol,
                    issued_at=issued_at,
                    cutoff=cutoff,
                    reason="future_graph_snapshot",
                    snapshot_id=snapshot.snapshot_id,
                )
        else:
            snapshots = await graph.list_snapshots(100, created_before=cutoff)
            if not snapshots:
                return _unavailable(
                    event_id=event.id,
                    symbol=symbol,
                    issued_at=issued_at,
                    cutoff=cutoff,
                    reason="graph_snapshot_unavailable",
                )
            payload_snapshot_id = snapshots[0].snapshot_id
        snapshot_id = payload.graph_snapshot_id or payload_snapshot_id
        projection = await graph.project_event(event, snapshot_id=snapshot_id)
    except Exception as exc:
        return _unavailable(
            event_id=event.id,
            symbol=symbol,
            issued_at=issued_at,
            cutoff=cutoff,
            reason=f"graph_unavailable:{type(exc).__name__}",
        )

    exposure = next((item for item in projection.companies if item.symbol.upper() == symbol), None)
    if exposure is None or _utc(event.timestamp) > cutoff:
        return _unavailable(
            event_id=event.id,
            symbol=symbol,
            issued_at=issued_at,
            cutoff=cutoff,
            reason="insufficient_graph_exposure",
            snapshot_id=snapshot_id,
        )
    universe = get_universe()
    repository = MarketBarRepository(session)
    asset_bars = await repository.get_bars(symbol, Interval.M1, end=cutoff, limit=2000)
    market_symbol = universe.market_benchmark
    sector_symbol = universe.sector_benchmark_for(symbol)
    market_bars = await repository.get_bars(market_symbol, Interval.M1, end=cutoff, limit=2000)
    sector_bars = (
        market_bars
        if sector_symbol == market_symbol
        else await repository.get_bars(sector_symbol, Interval.M1, end=cutoff, limit=2000)
    )
    try:
        features = build_feature_vector(
            event=event,
            symbol=symbol,
            issuance_timestamp=issued_at,
            data_cutoff_at=cutoff,
            asset_bars=asset_bars,
            market_bars=market_bars,
            sector_bars=sector_bars,
            exposure=exposure,
        )
    except FeatureLeakageError as exc:
        return _unavailable(
            event_id=event.id,
            symbol=symbol,
            issued_at=issued_at,
            cutoff=cutoff,
            reason=str(exc),
            snapshot_id=snapshot_id,
        )
    if not asset_bars or not market_bars or not sector_bars:
        return _unavailable(
            event_id=event.id,
            symbol=symbol,
            issued_at=issued_at,
            cutoff=cutoff,
            reason="insufficient_market_history",
            snapshot_id=snapshot_id,
        )
    returns = []
    for previous, current in pairwise(asset_bars):
        if previous.close > 0 and current.close > 0:
            returns.append(math.log(current.close / previous.close))
    har = HARVolatilityModel()
    volatility = {
        horizon: har.fit_predict(returns, days) for horizon, days in FORECAST_HORIZONS.items()
    }
    result = generate_forecast(
        event_id=event.id,
        symbol=symbol,
        issued_at=issued_at,
        data_cutoff_at=cutoff,
        graph_snapshot_id=snapshot_id,
        features=features,
        bundle=artifact,
        volatility=volatility,
        target_timestamps=_future_timestamps(cutoff),
        event_confidence=float(event.confidence),
    )
    return _result_out(result)
