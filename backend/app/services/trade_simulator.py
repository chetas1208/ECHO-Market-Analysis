"""Persistence boundary for deterministic paper simulations."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError
from app.forecasting.simulator import SimulationConfig, SimulationPoint, simulate_trade
from app.market.types import Interval
from app.models import (
    ForecastPoint,
    ForecastRun,
    PortfolioSnapshot,
    SimulatedTrade,
    SimulatedTradeEvent,
)
from app.repositories.market import MarketBarRepository
from app.schemas.ledger import SimulationCreateIn


class TradeSimulationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.market = MarketBarRepository(session)

    async def create(self, forecast_id: uuid.UUID, request: SimulationCreateIn) -> SimulatedTrade:
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
        if not points:
            raise ConflictError("forecast vintage has no forecast points")
        horizon = request.horizon or run.recommended_horizon
        point = next((item for item in points if item.horizon == horizon), None)
        if point is None:
            raise ConflictError(f"horizon '{horizon}' is unavailable for this vintage")
        config = SimulationConfig(
            initial_equity=request.initial_equity,
            risk_budget=request.risk_budget,
            min_q50_abs=request.min_q50_abs,
            probability_threshold=request.probability_threshold,
            max_interval_width=request.max_interval_width,
            max_position_pct=request.max_position_pct,
            commission_bps=request.commission_bps,
            spread_bps=request.spread_bps,
            slippage_bps=request.slippage_bps,
            stop_multiple=request.stop_multiple,
            strategy_version=request.strategy_version,
            hedge_symbol=request.hedge_symbol.upper() if request.hedge_symbol else None,
            hedge_ratio=request.hedge_ratio,
            mode=request.mode,
        )
        bars = await self.market.get_bars(
            run.symbol,
            Interval.M1,
            start=run.data_cutoff_at,
            limit=2000,
        )
        hedge_bars = (
            await self.market.get_bars(
                config.hedge_symbol, Interval.M1, start=run.data_cutoff_at, limit=2000
            )
            if config.hedge_symbol
            else None
        )
        outcome = simulate_trade(
            symbol=run.symbol,
            decision_timestamp=run.prediction_timestamp,
            point=SimulationPoint(
                horizon=point.horizon,
                target_timestamp=point.target_timestamp,
                q10=float(point.q10),
                q50=float(point.q50),
                q90=float(point.q90),
                probability_positive=float(point.probability_positive),
                risk=float(point.forecast_risk) if point.forecast_risk is not None else None,
            ),
            bars=bars,
            config=config,
            ood_status=run.ood_status or "UNKNOWN",
            abstention_state=run.abstention_state or "NONE",
            hedge_bars=hedge_bars,
        )
        existing = await self.session.scalar(
            select(SimulatedTrade).where(SimulatedTrade.plan_hash == outcome.plan_hash)
        )
        if existing is not None:
            return existing
        trade = SimulatedTrade(
            forecast_run_id=forecast_id,
            symbol=outcome.symbol,
            side=outcome.side,
            decision_timestamp=outcome.decision_timestamp,
            entry_timestamp=outcome.entry_timestamp,
            entry_price=outcome.entry_price,
            planned_exit_horizon=outcome.planned_exit_horizon,
            planned_exit_timestamp=outcome.planned_exit_timestamp,
            position_size=outcome.position_size,
            notional=outcome.notional,
            hedge_symbol=outcome.hedge_symbol,
            hedge_ratio=outcome.hedge_ratio,
            stop_type=outcome.stop_type,
            stop_value=outcome.stop_value,
            strategy_version=config.strategy_version,
            config_hash=config.config_hash,
            status=outcome.status,
            gross_pnl=outcome.gross_pnl,
            costs=outcome.costs,
            hedge_pnl=outcome.hedge_pnl,
            net_pnl=outcome.net_pnl,
            return_on_allocated_capital=outcome.return_on_allocated_capital,
            plan_hash=outcome.plan_hash,
            metadata={
                "reason": outcome.reason,
                "mode": config.mode,
                "initial_equity": config.initial_equity,
                "risk_budget": config.risk_budget,
                "assumptions": {
                    "entry": "first bar strictly after decision timestamp at open",
                    "exit": "first bar at or after target timestamp at close",
                    "stop": "volatility stop checked conservatively before horizon exit",
                    "costs": {
                        "commission_bps": config.commission_bps,
                        "spread_bps": config.spread_bps,
                        "slippage_bps": config.slippage_bps,
                    },
                },
            },
        )
        self.session.add(trade)
        await self.session.flush()
        events = [
            SimulatedTradeEvent(
                simulated_trade_id=trade.id,
                state="PLANNED",
                event_timestamp=outcome.decision_timestamp,
                metadata={"reason": outcome.reason},
            )
        ]
        if outcome.entry_timestamp is not None:
            events.append(
                SimulatedTradeEvent(
                    simulated_trade_id=trade.id,
                    state="OPEN",
                    event_timestamp=outcome.entry_timestamp,
                    price=outcome.entry_price,
                    quantity=outcome.position_size,
                )
            )
        terminal = outcome.status
        if terminal != "OPEN" and terminal != "PLANNED":
            events.append(
                SimulatedTradeEvent(
                    simulated_trade_id=trade.id,
                    state=terminal,
                    event_timestamp=outcome.exit_timestamp or outcome.decision_timestamp,
                    price=outcome.exit_price,
                    quantity=outcome.position_size,
                    realized_pnl=outcome.net_pnl,
                    costs=outcome.costs,
                )
            )
        self.session.add_all(events)
        await self.session.commit()
        return trade

    async def get(self, trade_id: uuid.UUID) -> SimulatedTrade:
        trade = await self.session.get(SimulatedTrade, trade_id)
        if trade is None:
            raise NotFoundError(f"Simulation '{trade_id}' not found")
        return trade

    async def portfolio(self, *, initial_equity: float = 100_000.0) -> dict[str, Any]:
        trades = list((await self.session.scalars(select(SimulatedTrade))).all())
        realized = sum(
            float(trade.net_pnl) for trade in trades if trade.status in {"CLOSED", "STOPPED"}
        )
        open_trades = [trade for trade in trades if trade.status == "OPEN"]
        gross = sum(float(trade.notional) for trade in open_trades)
        net = sum(
            float(trade.notional) * (1 if trade.side == "LONG" else -1) for trade in open_trades
        )
        return {
            "initial_equity": initial_equity,
            "cash": initial_equity + realized,
            "gross_exposure": gross,
            "net_exposure": net,
            "equity": initial_equity + realized,
            "realized_pnl": realized,
            "unrealized_pnl": 0.0,
            "trade_count": len(trades),
        }

    async def snapshot(
        self, *, config_hash: str, timestamp: datetime | None = None
    ) -> PortfolioSnapshot:
        state = await self.portfolio()
        snapshot = PortfolioSnapshot(
            snapshot_timestamp=(timestamp or datetime.now(UTC)).astimezone(UTC),
            cash=state["cash"],
            gross_exposure=state["gross_exposure"],
            net_exposure=state["net_exposure"],
            equity=state["equity"],
            realized_pnl=state["realized_pnl"],
            unrealized_pnl=state["unrealized_pnl"],
            config_hash=config_hash,
        )
        self.session.add(snapshot)
        await self.session.commit()
        return snapshot
