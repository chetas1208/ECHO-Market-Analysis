"""Chronological ECHO strategy replay using the Day 7 execution primitive."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from app.backtesting.clock import utc
from app.backtesting.datasets import BacktestCase, dataset_hash
from app.backtesting.metrics import Metrics, calculate_metrics
from app.forecasting.simulator import SimulationConfig, SimulationOutcome, simulate_trade
from app.strategy.policy import (
    StrategyAction,
    StrategyConfig,
    StrategyDecision,
    StrategyInput,
    decide,
)


@dataclass(frozen=True)
class BacktestTrade:
    case_key: str
    event_id: str
    event_class: str
    symbol: str
    sector: str
    side: str
    signal_timestamp: datetime
    entry_timestamp: datetime | None
    exit_timestamp: datetime | None
    horizon: str
    forecast_q50: float | None
    probability_positive: float | None
    graph_exposure: float | None
    cause_score: float | None
    absorption_ratio: float | None
    decision_reasons: tuple[str, ...]
    entry_price: float | None
    exit_price: float | None
    costs: float
    gross_pnl: float
    net_pnl: float
    status: str
    exit_reason: str | None
    notional: float

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["signal_timestamp"] = self.signal_timestamp.isoformat()
        value["entry_timestamp"] = (
            self.entry_timestamp.isoformat() if self.entry_timestamp else None
        )
        value["exit_timestamp"] = self.exit_timestamp.isoformat() if self.exit_timestamp else None
        value["decision_reasons"] = list(self.decision_reasons)
        return value


@dataclass(frozen=True)
class BacktestResult:
    run_id: str
    strategy_version: str
    config_hash: str
    dataset_hash: str
    split: str
    trades: tuple[BacktestTrade, ...]
    equity: tuple[dict[str, Any], ...]
    metrics: Metrics
    strategy_config: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "strategy_version": self.strategy_version,
            "config_hash": self.config_hash,
            "dataset_hash": self.dataset_hash,
            "split": self.split,
            "metrics": self.metrics.as_dict(),
            "strategy_config": self.strategy_config,
            "metadata": self.metadata,
            "trades": [trade.as_dict() for trade in self.trades],
            "equity": list(self.equity),
        }


def _run_id(strategy: StrategyConfig, cases: list[BacktestCase], split: str) -> str:
    seed = f"echo-backtest-v4:{strategy.config_hash}:{dataset_hash(cases)}:{split}"
    return hashlib.sha256(seed.encode()).hexdigest()[:20]


class BacktestEngine:
    """Replay cases in timestamp order; no strategy callback receives future bars."""

    def __init__(
        self, strategy: StrategyConfig | None = None, *, initial_equity: float = 100_000.0
    ) -> None:
        self.strategy = strategy or StrategyConfig()
        if initial_equity <= 0:
            raise ValueError("initial_equity must be positive")
        self.initial_equity = initial_equity

    def _inputs(self, case: BacktestCase) -> StrategyInput:
        point = case.forecast
        return StrategyInput(
            symbol=case.symbol,
            event_class=case.event_class,
            event_confidence=case.event_confidence,
            graph_exposure=case.graph_exposure,
            graph_confidence=case.graph_confidence,
            cause_score=case.cause_score,
            cause_direction=case.cause_direction,
            observed_residual=case.observed_residual,
            residual_z=case.residual_z,
            sector_residual_z=case.sector_residual_z,
            volume_z=case.volume_z,
            response_state=case.response_state,
            q10=point.q10,
            q50=point.q50,
            q90=point.q90,
            probability_positive=point.probability_positive,
            horizon_days=point.horizon and int(point.horizon.removesuffix("D")),
            market_fresh=case.market_fresh,
            already_priced=case.already_priced,
        )

    def run(self, cases: list[BacktestCase], *, split: str = "TEST") -> BacktestResult:
        if not cases:
            raise ValueError("backtest cases cannot be empty")
        ordered = sorted(
            cases, key=lambda item: (utc(item.decision_timestamp), item.event_id, item.symbol)
        )
        open_until: list[tuple[datetime, str, float]] = []
        equity = self.initial_equity
        high_water = equity
        daily_pnl: dict[str, float] = {}
        trades: list[BacktestTrade] = []
        equity_rows: list[dict[str, Any]] = [
            {
                "timestamp": utc(ordered[0].decision_timestamp).isoformat(),
                "equity": equity,
                "drawdown": 0.0,
                "gross_exposure": 0.0,
                "net_exposure": 0.0,
            }
        ]
        returns: list[float] = []
        trade_returns: list[float] = []
        holding_days: list[float] = []
        notionals: list[float] = []
        sides: list[str] = []
        kill_switch = False
        for case in ordered:
            now = utc(case.decision_timestamp)
            open_until = [item for item in open_until if item[0] > now]
            current_gross = sum(item[2] for item in open_until) / equity if equity else 0.0
            portfolio_allows = (
                not kill_switch
                and len(open_until) < self.strategy.max_positions
                and current_gross < self.strategy.max_total_gross_pct
            )
            sector_count = sum(1 for _, sector, _ in open_until if sector == case.sector)
            sector_gross = (
                sum(item[2] for item in open_until if item[1] == case.sector) / equity
                if equity
                else 0.0
            )
            portfolio_allows = (
                portfolio_allows
                and sector_count < self.strategy.max_sector_positions
                and sector_gross < self.strategy.max_sector_gross_pct
            )
            if self.strategy.daily_loss_limit is not None:
                portfolio_allows = portfolio_allows and daily_pnl.get(
                    now.date().isoformat(), 0.0
                ) > -(equity * self.strategy.daily_loss_limit)
            decision = decide(self._inputs(case), self.strategy)
            if not portfolio_allows and decision.action != StrategyAction.ABSTAIN:
                decision = StrategyDecision(
                    StrategyAction.ABSTAIN,
                    (*decision.reason_codes, "PORTFOLIO_LIMIT"),
                    decision.score,
                    decision.absorption_ratio,
                    decision.direction,
                    decision.metadata,
                )
            simulation = self._simulate(case, decision, equity)
            if (
                simulation.side != "NO_TRADE"
                and simulation.entry_timestamp is not None
                and simulation.exit_timestamp is not None
            ):
                notional = simulation.notional
                if notional / equity > self.strategy.max_position_pct + 1e-9:
                    decision = StrategyDecision(
                        StrategyAction.ABSTAIN,
                        (*decision.reason_codes, "POSITION_LIMIT"),
                        decision.score,
                        decision.absorption_ratio,
                        decision.direction,
                        decision.metadata,
                    )
                    simulation = self._simulate(case, decision, equity)
            if simulation.side != "NO_TRADE" and simulation.exit_timestamp is not None:
                open_until.append(
                    (utc(simulation.exit_timestamp), case.sector, simulation.notional)
                )
                equity += simulation.net_pnl
                high_water = max(high_water, equity)
                day = now.date().isoformat()
                daily_pnl[day] = daily_pnl.get(day, 0.0) + simulation.net_pnl
                trade_return = simulation.return_on_allocated_capital or 0.0
                returns.append(simulation.net_pnl / max(equity - simulation.net_pnl, 1e-9))
                trade_returns.append(trade_return)
                holding_days.append(
                    max(
                        0.0,
                        (
                            utc(simulation.exit_timestamp) - utc(simulation.entry_timestamp)
                        ).total_seconds()
                        / 86400,
                    )
                )
                notionals.append(simulation.notional)
                sides.append(simulation.side)
            trades.append(self._trade(case, decision, simulation))
            drawdown = (high_water - equity) / high_water if high_water else 0.0
            if drawdown >= self.strategy.max_drawdown:
                kill_switch = True
            equity_rows.append(
                {
                    "timestamp": now.isoformat(),
                    "equity": equity,
                    "drawdown": drawdown,
                    "gross_exposure": sum(item[2] for item in open_until) / max(equity, 1e-9),
                    "net_exposure": sum(item[2] for item in open_until) / max(equity, 1e-9),
                }
            )
        first = utc(ordered[0].decision_timestamp)
        last = utc(ordered[-1].decision_timestamp)
        weeks = max((last - first).total_seconds() / 604800, 0.0)
        metrics = calculate_metrics(
            initial_equity=self.initial_equity,
            equity=[float(row["equity"]) for row in equity_rows],
            returns=returns,
            trade_returns=trade_returns,
            sides=sides,
            holding_days=holding_days,
            notional=notionals,
            weeks=weeks,
        )
        run_id = _run_id(self.strategy, ordered, split)
        return BacktestResult(
            run_id=run_id,
            strategy_version=self.strategy.strategy_version,
            config_hash=self.strategy.config_hash,
            dataset_hash=dataset_hash(ordered),
            split=split,
            trades=tuple(trades),
            equity=tuple(equity_rows),
            metrics=metrics,
            strategy_config=self.strategy.as_dict(),
            metadata={
                "mode": "HISTORICAL_REPLAY",
                "sample_status": metrics.status,
                "case_count": len(ordered),
                "start": first.isoformat(),
                "end": last.isoformat(),
                "event_groups": len({case.event_group for case in ordered}),
                "future_access_policy": "strictly_after_decision_for_execution",
            },
        )

    def _simulate(
        self, case: BacktestCase, decision: StrategyDecision, equity: float | None = None
    ) -> SimulationOutcome:
        equity = equity or self.initial_equity
        point = case.forecast
        if decision.action == StrategyAction.ABSTAIN:
            point = type(point)(
                horizon=point.horizon,
                target_timestamp=point.target_timestamp,
                q10=0.0,
                q50=0.0,
                q90=0.0,
                probability_positive=0.5,
                risk=point.risk,
            )
        else:
            point = type(point)(
                horizon=point.horizon,
                target_timestamp=point.target_timestamp,
                q10=point.q10,
                q50=abs(point.q50) if decision.action == StrategyAction.LONG else -abs(point.q50),
                q90=point.q90,
                probability_positive=point.probability_positive,
                risk=point.risk,
            )
        config = SimulationConfig(
            initial_equity=equity,
            risk_budget=equity * self.strategy.risk_per_trade,
            min_q50_abs=self.strategy.min_q50_abs,
            probability_threshold=self.strategy.min_probability,
            max_interval_width=self.strategy.max_interval_width,
            max_position_pct=self.strategy.max_position_pct,
            commission_bps=2.0 * self.strategy.cost_multiplier,
            spread_bps=5.0 * self.strategy.cost_multiplier,
            slippage_bps=5.0 * self.strategy.cost_multiplier,
            stop_multiple=self.strategy.stop_atr_multiple,
            strategy_version=self.strategy.strategy_version,
            hedge_symbol="SPY" if self.strategy.hedge.value == "SPY" else None,
            hedge_ratio=0.25 if self.strategy.hedge.value != "NONE" else 0.0,
        )
        return simulate_trade(
            symbol=case.symbol,
            decision_timestamp=case.decision_timestamp,
            point=point,
            bars=list(case.bars),
            config=config,
            ood_status="IN_DISTRIBUTION",
            abstention_state="NONE"
            if decision.action != StrategyAction.ABSTAIN
            else "POLICY_ABSTAIN",
            hedge_bars=list(case.hedge_bars),
        )

    @staticmethod
    def _trade(
        case: BacktestCase, decision: StrategyDecision, outcome: SimulationOutcome
    ) -> BacktestTrade:
        return BacktestTrade(
            case_key=case.case_key,
            event_id=case.event_id,
            event_class=case.event_class,
            symbol=case.symbol.upper(),
            sector=case.sector,
            side=outcome.side,
            signal_timestamp=utc(case.decision_timestamp),
            entry_timestamp=outcome.entry_timestamp,
            exit_timestamp=outcome.exit_timestamp,
            horizon=case.forecast.horizon,
            forecast_q50=case.forecast.q50,
            probability_positive=case.forecast.probability_positive,
            graph_exposure=case.graph_exposure,
            cause_score=case.cause_score,
            absorption_ratio=decision.absorption_ratio,
            decision_reasons=decision.reason_codes,
            entry_price=outcome.entry_price,
            exit_price=outcome.exit_price,
            costs=outcome.costs,
            gross_pnl=outcome.gross_pnl,
            net_pnl=outcome.net_pnl,
            status=outcome.status,
            exit_reason=outcome.reason,
            notional=outcome.notional,
        )
