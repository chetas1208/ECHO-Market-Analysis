"""Resolve realized CAR observations using the Day 6 target definition."""

from __future__ import annotations

import math
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError
from app.forecasting.targets import TargetConstructionError, build_car_targets
from app.market.types import Interval
from app.market.universe import get_universe
from app.models import ForecastPoint, ForecastRun
from app.repositories.market import MarketBarRepository
from app.services.prediction_ledger import PredictionLedgerService


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC)


class ForecastActualCollector:
    """Append due target observations; it never writes forecast rows."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.market = MarketBarRepository(session)
        self.ledger = PredictionLedgerService(session)

    async def collect_due(
        self, forecast_id: uuid.UUID, *, as_of: datetime, source: str = "market_observations"
    ) -> int:
        as_of = _utc(as_of)
        run = await self.session.get(ForecastRun, forecast_id)
        if run is None:
            raise NotFoundError(f"Forecast vintage '{forecast_id}' not found")
        points = list(
            (
                await self.session.scalars(
                    select(ForecastPoint)
                    .where(ForecastPoint.forecast_run_id == forecast_id)
                    .order_by(ForecastPoint.horizon_trading_days)
                )
            ).all()
        )
        universe = get_universe()
        market_symbol = universe.market_benchmark
        sector_symbol = universe.sector_benchmark_for(run.symbol)
        asset_bars = await self.market.get_bars(run.symbol, Interval.M1, end=as_of, limit=2000)
        market_bars = await self.market.get_bars(market_symbol, Interval.M1, end=as_of, limit=2000)
        sector_bars = (
            market_bars
            if sector_symbol == market_symbol
            else await self.market.get_bars(sector_symbol, Interval.M1, end=as_of, limit=2000)
        )
        beta_market = run.feature_snapshot.get("beta_market")
        beta_sector = run.feature_snapshot.get("beta_sector")
        if beta_market is None or beta_sector is None:
            raise ConflictError(
                "forecast vintage lacks the beta snapshot required for CAR evaluation"
            )
        try:
            targets = build_car_targets(
                asset_bars=asset_bars,
                market_bars=market_bars,
                sector_bars=sector_bars,
                issuance_timestamp=run.prediction_timestamp,
                data_cutoff_at=run.data_cutoff_at,
                beta_market=float(beta_market),
                beta_sector=float(beta_sector),
            )
        except TargetConstructionError as exc:
            raise ConflictError(str(exc)) from exc
        appended = 0
        for point in points:
            target = targets.get(point.horizon)
            if target is None or _utc(target.target_timestamp) > as_of:
                continue
            asset_close = next(
                (
                    bar
                    for bar in reversed(asset_bars)
                    if _utc(bar.timestamp) <= target.target_timestamp
                ),
                None,
            )
            market_close = next(
                (
                    bar
                    for bar in reversed(market_bars)
                    if _utc(bar.timestamp) <= target.target_timestamp
                ),
                None,
            )
            sector_close = next(
                (
                    bar
                    for bar in reversed(sector_bars)
                    if _utc(bar.timestamp) <= target.target_timestamp
                ),
                None,
            )
            if asset_close is None or market_close is None or sector_close is None:
                continue
            asset_start = next(
                (
                    bar
                    for bar in reversed(asset_bars)
                    if _utc(bar.timestamp) <= run.prediction_timestamp
                ),
                None,
            )
            market_start = next(
                (
                    bar
                    for bar in reversed(market_bars)
                    if _utc(bar.timestamp) <= run.prediction_timestamp
                ),
                None,
            )
            sector_start = next(
                (
                    bar
                    for bar in reversed(sector_bars)
                    if _utc(bar.timestamp) <= run.prediction_timestamp
                ),
                None,
            )
            if asset_start is None or market_start is None or sector_start is None:
                continue
            asset_return = math.log(float(asset_close.close) / float(asset_start.close))
            market_return = math.log(float(market_close.close) / float(market_start.close))
            sector_return = math.log(float(sector_close.close) / float(sector_start.close))
            await self.ledger.append_actual(
                forecast_id,
                {
                    "symbol": run.symbol,
                    "horizon": point.horizon,
                    "observed_at": as_of,
                    "market_timestamp": target.target_timestamp,
                    "actual_price": float(asset_close.close),
                    "actual_return": asset_return,
                    "actual_abnormal_return": target.cumulative_abnormal_return,
                    "market_return": market_return,
                    "sector_return": sector_return,
                    "source": source,
                },
            )
            appended += 1
        return appended
