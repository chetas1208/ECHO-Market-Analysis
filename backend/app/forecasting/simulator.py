"""Deterministic, bar-based paper simulation for frozen forecast vintages."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from app.market.types import Bar

TradeSide = Literal["LONG", "SHORT", "NO_TRADE"]
TradeStatus = Literal[
    "PLANNED",
    "OPEN",
    "CLOSED",
    "STOPPED",
    "EXPIRED",
    "CANCELLED_BEFORE_ENTRY",
    "NO_TRADE",
]


@dataclass(frozen=True)
class SimulationConfig:
    initial_equity: float = 100_000.0
    risk_budget: float = 1_000.0
    min_q50_abs: float = 0.005
    probability_threshold: float = 0.55
    max_interval_width: float = 0.25
    max_position_pct: float = 0.20
    commission_bps: float = 0.0
    spread_bps: float = 5.0
    slippage_bps: float = 5.0
    stop_multiple: float = 2.0
    strategy_version: str = "echo-sim-v1"
    hedge_symbol: str | None = None
    hedge_ratio: float = 0.0
    mode: Literal["HISTORICAL_REPLAY", "LIVE_SIMULATION"] = "HISTORICAL_REPLAY"

    def __post_init__(self) -> None:
        if self.initial_equity <= 0 or self.risk_budget <= 0:
            raise ValueError("equity and risk budget must be positive")
        if not self.min_q50_abs >= 0 or not 0 <= self.probability_threshold <= 1:
            raise ValueError("signal thresholds are invalid")
        if self.max_interval_width <= 0 or not 0 < self.max_position_pct <= 1:
            raise ValueError("position limits are invalid")
        if min(self.commission_bps, self.spread_bps, self.slippage_bps) < 0:
            raise ValueError("costs cannot be negative")
        if self.stop_multiple <= 0 or not 0 <= self.hedge_ratio <= 1:
            raise ValueError("stop and hedge configuration are invalid")

    def as_dict(self) -> dict[str, object]:
        return {
            "initial_equity": self.initial_equity,
            "risk_budget": self.risk_budget,
            "min_q50_abs": self.min_q50_abs,
            "probability_threshold": self.probability_threshold,
            "max_interval_width": self.max_interval_width,
            "max_position_pct": self.max_position_pct,
            "commission_bps": self.commission_bps,
            "spread_bps": self.spread_bps,
            "slippage_bps": self.slippage_bps,
            "stop_multiple": self.stop_multiple,
            "strategy_version": self.strategy_version,
            "hedge_symbol": self.hedge_symbol,
            "hedge_ratio": self.hedge_ratio,
            "mode": self.mode,
        }

    @property
    def config_hash(self) -> str:
        payload = json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()


@dataclass(frozen=True)
class SimulationPoint:
    horizon: str
    target_timestamp: datetime
    q10: float
    q50: float
    q90: float
    probability_positive: float
    risk: float | None


@dataclass(frozen=True)
class SimulationOutcome:
    symbol: str
    side: TradeSide
    decision_timestamp: datetime
    entry_timestamp: datetime | None
    entry_price: float | None
    planned_exit_horizon: str
    planned_exit_timestamp: datetime
    position_size: float
    notional: float
    hedge_symbol: str | None
    hedge_ratio: float
    stop_type: str | None
    stop_value: float | None
    status: TradeStatus
    gross_pnl: float
    costs: float
    hedge_pnl: float
    net_pnl: float
    return_on_allocated_capital: float | None
    plan_hash: str
    reason: str | None
    exit_timestamp: datetime | None
    exit_price: float | None


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(UTC)


def _hash_plan(values: dict[str, object]) -> str:
    normalized = json.dumps(values, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(normalized.encode()).hexdigest()


def _next_bar(bars: list[Bar], timestamp: datetime) -> Bar | None:
    cutoff = _utc(timestamp)
    return next(
        (
            bar
            for bar in sorted(bars, key=lambda item: _utc(item.timestamp))
            if _utc(bar.timestamp) > cutoff
        ),
        None,
    )


def _bar_at_or_after(bars: list[Bar], timestamp: datetime) -> Bar | None:
    target = _utc(timestamp)
    return next(
        (
            bar
            for bar in sorted(bars, key=lambda item: _utc(item.timestamp))
            if _utc(bar.timestamp) >= target
        ),
        None,
    )


def simulate_trade(
    *,
    symbol: str,
    decision_timestamp: datetime,
    point: SimulationPoint,
    bars: list[Bar],
    config: SimulationConfig,
    ood_status: str = "IN_DISTRIBUTION",
    abstention_state: str = "NONE",
    hedge_bars: list[Bar] | None = None,
) -> SimulationOutcome:
    """Simulate only with bars strictly after the frozen decision timestamp."""

    decision = _utc(decision_timestamp)
    interval_width = point.q90 - point.q10
    side: TradeSide = "NO_TRADE"
    reason: str | None = None
    if ood_status != "IN_DISTRIBUTION":
        reason = "out_of_distribution"
    elif abstention_state != "NONE":
        reason = "forecast_abstained"
    elif abs(point.q50) < config.min_q50_abs:
        reason = "q50_below_threshold"
    elif interval_width > config.max_interval_width:
        reason = "interval_too_wide"
    elif point.q50 > 0 and point.probability_positive >= config.probability_threshold:
        side = "LONG"
    elif point.q50 < 0 and point.probability_positive <= 1 - config.probability_threshold:
        side = "SHORT"
    else:
        reason = "probability_threshold_not_met"

    base_plan = {
        "symbol": symbol.upper(),
        "side": side,
        "decision_timestamp": decision.isoformat(),
        "horizon": point.horizon,
        "target_timestamp": _utc(point.target_timestamp).isoformat(),
        "q10": point.q10,
        "q50": point.q50,
        "q90": point.q90,
        "probability_positive": point.probability_positive,
        "config_hash": config.config_hash,
    }
    if side == "NO_TRADE":
        return SimulationOutcome(
            symbol=symbol.upper(),
            side=side,
            decision_timestamp=decision,
            entry_timestamp=None,
            entry_price=None,
            planned_exit_horizon=point.horizon,
            planned_exit_timestamp=_utc(point.target_timestamp),
            position_size=0.0,
            notional=0.0,
            hedge_symbol=config.hedge_symbol,
            hedge_ratio=config.hedge_ratio,
            stop_type=None,
            stop_value=None,
            status="NO_TRADE",
            gross_pnl=0.0,
            costs=0.0,
            hedge_pnl=0.0,
            net_pnl=0.0,
            return_on_allocated_capital=None,
            plan_hash=_hash_plan({**base_plan, "reason": reason}),
            reason=reason,
            exit_timestamp=None,
            exit_price=None,
        )

    entry_bar = _next_bar(bars, decision)
    if entry_bar is None:
        return SimulationOutcome(
            symbol=symbol.upper(),
            side=side,
            decision_timestamp=decision,
            entry_timestamp=None,
            entry_price=None,
            planned_exit_horizon=point.horizon,
            planned_exit_timestamp=_utc(point.target_timestamp),
            position_size=0.0,
            notional=0.0,
            hedge_symbol=config.hedge_symbol,
            hedge_ratio=config.hedge_ratio,
            stop_type=None,
            stop_value=None,
            status="CANCELLED_BEFORE_ENTRY",
            gross_pnl=0.0,
            costs=0.0,
            hedge_pnl=0.0,
            net_pnl=0.0,
            return_on_allocated_capital=None,
            plan_hash=_hash_plan({**base_plan, "reason": "entry_bar_unavailable"}),
            reason="entry_bar_unavailable",
            exit_timestamp=None,
            exit_price=None,
        )

    direction = 1.0 if side == "LONG" else -1.0
    friction_rate = (config.spread_bps / 2 + config.slippage_bps) / 10_000
    entry_price = float(entry_bar.open) * (1 + direction * friction_rate)
    risk_per_share = max(abs(point.q90 - point.q10) * entry_price / 2, entry_price * 0.01)
    size = min(
        config.risk_budget / risk_per_share,
        config.initial_equity * config.max_position_pct / entry_price,
    )
    size = max(0.0, size)
    notional = size * entry_price
    stop_distance = config.stop_multiple * risk_per_share
    stop_value = entry_price - direction * stop_distance
    planned_exit = _utc(point.target_timestamp)
    exit_bar = _bar_at_or_after(bars, planned_exit)
    status: TradeStatus = "OPEN" if exit_bar is None else "CLOSED"
    exit_timestamp: datetime | None = None
    exit_price: float | None = None
    if exit_bar is not None:
        exit_timestamp = _utc(exit_bar.timestamp)
        stop_bar = None
        for bar in bars:
            bar_time = _utc(bar.timestamp)
            if entry_bar.timestamp < bar_time <= exit_bar.timestamp and (
                (side == "LONG" and bar.low <= stop_value)
                or (side == "SHORT" and bar.high >= stop_value)
            ):
                stop_bar = bar
                break
        if stop_bar is not None:
            status = "STOPPED"
            exit_timestamp = _utc(stop_bar.timestamp)
            exit_price = stop_value
        else:
            raw_exit = float(exit_bar.close)
            exit_price = raw_exit * (1 - direction * friction_rate)
    gross_pnl = 0.0 if exit_price is None else direction * (exit_price - entry_price) * size
    costs = (
        (entry_price * size + (exit_price or entry_price) * size) * config.commission_bps / 10_000
    )
    hedge_pnl = 0.0
    if config.hedge_symbol and config.hedge_ratio and hedge_bars and exit_timestamp is not None:
        hedge_entry = _next_bar(hedge_bars, decision)
        hedge_exit = _bar_at_or_after(hedge_bars, exit_timestamp)
        if hedge_entry and hedge_exit:
            hedge_size = notional * config.hedge_ratio / float(hedge_entry.open)
            hedge_pnl = (
                -direction * (float(hedge_exit.close) - float(hedge_entry.open)) * hedge_size
            )
    net_pnl = gross_pnl + hedge_pnl - costs
    allocated = notional if notional > 0 else None
    return SimulationOutcome(
        symbol=symbol.upper(),
        side=side,
        decision_timestamp=decision,
        entry_timestamp=_utc(entry_bar.timestamp),
        entry_price=entry_price,
        planned_exit_horizon=point.horizon,
        planned_exit_timestamp=planned_exit,
        position_size=size,
        notional=notional,
        hedge_symbol=config.hedge_symbol,
        hedge_ratio=config.hedge_ratio,
        stop_type="VOLATILITY" if stop_value else None,
        stop_value=stop_value,
        status=status,
        gross_pnl=gross_pnl,
        costs=costs,
        hedge_pnl=hedge_pnl,
        net_pnl=net_pnl,
        return_on_allocated_capital=net_pnl / allocated if allocated else None,
        plan_hash=_hash_plan(
            {
                **base_plan,
                "entry_timestamp": _utc(entry_bar.timestamp).isoformat(),
                "entry_price": entry_price,
                "position_size": size,
                "stop_value": stop_value,
            }
        ),
        reason=None if status == "CLOSED" or status == "STOPPED" else "exit_bar_unavailable",
        exit_timestamp=exit_timestamp,
        exit_price=exit_price,
    )
