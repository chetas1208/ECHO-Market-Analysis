"""Small, predeclared strategy-family and robustness evaluations."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from app.backtesting.datasets import BacktestCase
from app.backtesting.engine import BacktestEngine, BacktestResult
from app.strategy.policy import ConfirmationMode, StrategyConfig

FAMILY_NAMES = (
    "S0_BUY_HOLD_SPY",
    "S1_SIMPLE_MOMENTUM",
    "S2_MARKET_SHOCK_ONLY",
    "S3_GRAPH_EXPOSURE",
    "S4_GRAPH_ABSORPTION",
    "S5_GRAPH_ABSORPTION_CONFIRMATION",
    "S6_FULL_ECHO",
)


@dataclass(frozen=True)
class ResearchReport:
    family_results: dict[str, BacktestResult]
    ablations: dict[str, BacktestResult]
    robustness: dict[str, BacktestResult]
    trials_count: int


def _family_config(base: StrategyConfig, family: str) -> StrategyConfig:
    if family in {"S0_BUY_HOLD_SPY", "S1_SIMPLE_MOMENTUM"}:
        return replace(
            base,
            min_graph_exposure=0.0,
            min_graph_confidence=0.0,
            min_event_confidence=0.0,
            min_q50_abs=0.0,
            min_probability=0.5,
            confirmation=ConfirmationMode.NONE,
        )
    if family == "S2_MARKET_SHOCK_ONLY":
        return replace(
            base,
            min_graph_exposure=0.0,
            min_graph_confidence=0.0,
            min_event_confidence=0.0,
            max_absorption_ratio=1.0,
            confirmation=ConfirmationMode.NONE,
        )
    if family == "S3_GRAPH_EXPOSURE":
        return replace(base, max_absorption_ratio=1.0, confirmation=ConfirmationMode.NONE)
    if family == "S4_GRAPH_ABSORPTION":
        return replace(base, confirmation=ConfirmationMode.NONE)
    return base


def run_research(cases: list[BacktestCase], base: StrategyConfig | None = None) -> ResearchReport:
    if not cases:
        raise ValueError("research cases cannot be empty")
    base = base or StrategyConfig()
    family_results = {
        name: BacktestEngine(_family_config(base, name)).run(cases, split="VALIDATION")
        for name in FAMILY_NAMES
    }
    ablation_configs = {
        "FULL_MINUS_GRAPH": replace(base, min_graph_exposure=0.0, min_graph_confidence=0.0),
        "FULL_MINUS_ABSORPTION": replace(base, max_absorption_ratio=1.0),
        "FULL_MINUS_CONFIRMATION": replace(base, confirmation=ConfirmationMode.NONE),
        "FULL_MINUS_HEDGING": replace(base),
    }
    ablations = {
        name: BacktestEngine(config).run(cases, split="VALIDATION")
        for name, config in ablation_configs.items()
    }
    robustness = {
        f"COST_{multiplier:g}X": BacktestEngine(replace(base, cost_multiplier=multiplier)).run(
            cases, split="VALIDATION"
        )
        for multiplier in (1.0, 2.0, 3.0)
    }
    return ResearchReport(
        family_results=family_results,
        ablations=ablations,
        robustness=robustness,
        trials_count=len(family_results) + len(ablations) + len(robustness),
    )


def report_dict(report: ResearchReport) -> dict[str, Any]:
    return {
        "trials_count": report.trials_count,
        "families": {
            name: result.metrics.as_dict() for name, result in report.family_results.items()
        },
        "ablations": {name: result.metrics.as_dict() for name, result in report.ablations.items()},
        "robustness": {
            name: result.metrics.as_dict() for name, result in report.robustness.items()
        },
    }
