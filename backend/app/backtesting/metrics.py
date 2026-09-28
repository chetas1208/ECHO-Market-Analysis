"""Empirical portfolio metrics with explicit insufficient-sample states."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from statistics import median
from typing import Any


@dataclass(frozen=True)
class Metrics:
    status: str
    total_return: float
    annualized_return: float | None
    sharpe: float | None
    sortino: float | None
    max_drawdown: float
    calmar: float | None
    hit_rate: float | None
    profit_factor: float | None
    average_trade: float | None
    median_trade: float | None
    average_winner: float | None
    average_loser: float | None
    payoff_ratio: float | None
    turnover: float
    trades: int
    trades_per_week: float | None
    average_holding_days: float | None
    gross_exposure: float
    net_exposure: float
    long_trades: int
    short_trades: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def calculate_metrics(
    *,
    initial_equity: float,
    equity: list[float],
    returns: list[float],
    trade_returns: list[float],
    sides: list[str],
    holding_days: list[float],
    notional: list[float],
    weeks: float | None = None,
) -> Metrics:
    trades = len(trade_returns)
    total_return = (equity[-1] / initial_equity - 1) if equity else 0.0
    peak = initial_equity
    max_dd = 0.0
    for value in equity:
        peak = max(peak, value)
        max_dd = max(max_dd, (peak - value) / peak if peak else 0.0)
    annualized = (
        ((1 + total_return) ** (365 / max(1.0, (weeks or 0.0) * 7)) - 1)
        if weeks and total_return > -1 and trades >= 20
        else None
    )
    mean = sum(returns) / len(returns) if returns else None
    std = (
        math.sqrt(sum((value - mean) ** 2 for value in returns) / (len(returns) - 1))
        if len(returns) > 1 and mean is not None
        else None
    )
    downside = [min(value, 0.0) for value in returns]
    downside_std = (
        math.sqrt(sum(value * value for value in downside) / max(1, len(downside) - 1))
        if downside
        else None
    )
    sharpe = (mean / std * math.sqrt(252)) if std and len(returns) >= 20 else None
    sortino = (
        (mean / downside_std * math.sqrt(252)) if downside_std and len(returns) >= 20 else None
    )
    winners = [value for value in trade_returns if value > 0]
    losers = [value for value in trade_returns if value < 0]
    gross_win = sum(winners)
    gross_loss = abs(sum(losers))
    return Metrics(
        status="OK" if trades >= 20 else "INSUFFICIENT_DATA",
        total_return=total_return,
        annualized_return=annualized,
        sharpe=sharpe,
        sortino=sortino,
        max_drawdown=max_dd,
        calmar=(annualized / max_dd if annualized is not None and max_dd else None),
        hit_rate=(len(winners) / trades if trades else None),
        profit_factor=(gross_win / gross_loss if gross_loss else None),
        average_trade=(sum(trade_returns) / trades if trades else None),
        median_trade=median(trade_returns) if trade_returns else None,
        average_winner=(sum(winners) / len(winners) if winners else None),
        average_loser=(sum(losers) / len(losers) if losers else None),
        payoff_ratio=(
            (sum(winners) / len(winners)) / abs(sum(losers) / len(losers))
            if winners and losers
            else None
        ),
        turnover=sum(notional) / initial_equity,
        trades=trades,
        trades_per_week=(trades / weeks if weeks else None),
        average_holding_days=(sum(holding_days) / len(holding_days) if holding_days else None),
        gross_exposure=(sum(notional) / len(notional) / initial_equity if notional else 0.0),
        net_exposure=(
            sum(
                value if side == "LONG" else -value
                for value, side in zip(notional, sides, strict=True)
            )
            / len(notional)
            / initial_equity
            if notional
            else 0.0
        ),
        long_trades=sides.count("LONG"),
        short_trades=sides.count("SHORT"),
    )
