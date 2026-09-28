"""The Day 8 ECHO Residual Propagation policy.

The policy consumes only a frozen decision-time snapshot.  It deliberately returns
ABSTAIN with a reason instead of silently filling missing values or treating a
heuristic score as a probability.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml


class StrategyAction(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"
    ABSTAIN = "ABSTAIN"


class ConfirmationMode(StrEnum):
    NONE = "NONE"
    MODERATE = "MODERATE"
    STRICT = "STRICT"


class HedgeMode(StrEnum):
    NONE = "NONE"
    SPY = "SPY"
    SECTOR = "SECTOR"


@dataclass(frozen=True)
class StrategyConfig:
    """Registered strategy parameters; material edits require a new version."""

    strategy_version: str = "echo-rp-v1"
    min_graph_exposure: float = 0.20
    min_graph_confidence: float = 0.60
    min_event_confidence: float = 0.60
    min_probability: float = 0.60
    min_q50_abs: float = 0.005
    max_interval_width: float = 0.25
    max_absorption_ratio: float = 0.75
    already_priced_residual_z: float = 2.5
    confirmation: ConfirmationMode = ConfirmationMode.MODERATE
    max_horizon_days: int = 5
    entry_delay_minutes: int = 1
    risk_per_trade: float = 0.0075
    max_position_pct: float = 0.20
    max_positions: int = 5
    max_sector_positions: int = 2
    max_sector_gross_pct: float = 0.30
    max_total_gross_pct: float = 1.0
    max_drawdown: float = 0.05
    daily_loss_limit: float | None = 0.02
    stop_atr_multiple: float = 1.5
    hedge: HedgeMode = HedgeMode.NONE
    cost_multiplier: float = 1.0

    def __post_init__(self) -> None:
        if not self.strategy_version.strip():
            raise ValueError("strategy_version is required")
        if not 0 <= self.min_probability <= 1:
            raise ValueError("min_probability must be in [0, 1]")
        if self.min_q50_abs < 0 or self.max_interval_width <= 0:
            raise ValueError("forecast thresholds are invalid")
        if not 0 <= self.min_graph_confidence <= 1 or not 0 <= self.min_event_confidence <= 1:
            raise ValueError("confidence thresholds must be in [0, 1]")
        if self.min_graph_exposure < 0 or not 0 < self.max_absorption_ratio <= 1:
            raise ValueError("graph and absorption thresholds are invalid")
        if self.already_priced_residual_z <= 0 or self.max_horizon_days not in {1, 2, 5}:
            raise ValueError("strategy horizon or residual threshold is invalid")
        if self.entry_delay_minutes < 0 or not 0 < self.risk_per_trade <= 1:
            raise ValueError("execution or risk settings are invalid")
        if not 0 < self.max_position_pct <= 1 or self.max_positions < 1:
            raise ValueError("position settings are invalid")
        if self.max_sector_positions < 1 or not 0 < self.max_sector_gross_pct <= 1:
            raise ValueError("sector limits are invalid")
        if not 0 < self.max_total_gross_pct <= 1 or not 0 < self.max_drawdown < 1:
            raise ValueError("portfolio limits are invalid")
        if self.daily_loss_limit is not None and not 0 < self.daily_loss_limit < 1:
            raise ValueError("daily_loss_limit is invalid")
        if self.stop_atr_multiple <= 0 or self.cost_multiplier <= 0:
            raise ValueError("stop and cost settings are invalid")

    def as_dict(self) -> dict[str, Any]:
        values = asdict(self)
        values["confirmation"] = self.confirmation.value
        values["hedge"] = self.hedge.value
        return values

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> StrategyConfig:
        signal = value.get("signal", {})
        execution = value.get("execution", {})
        risk = value.get("risk", {})
        hedge = value.get("hedge", {})
        costs = value.get("costs", {})
        return cls(
            strategy_version=str(value.get("strategy_version", cls.strategy_version)),
            **{
                key: signal[key]
                for key in (
                    "min_graph_exposure",
                    "min_graph_confidence",
                    "min_event_confidence",
                    "min_probability",
                    "min_q50_abs",
                    "max_interval_width",
                    "max_absorption_ratio",
                    "already_priced_residual_z",
                )
                if key in signal
            },
            confirmation=ConfirmationMode(value.get("confirmation", ConfirmationMode.MODERATE)),
            max_horizon_days=max(
                int(str(execution.get("max_horizon_days", 5)).removesuffix("D")), 1
            ),
            entry_delay_minutes=int(execution.get("entry_delay_minutes", 1)),
            **{
                key: risk[key]
                for key in (
                    "risk_per_trade",
                    "max_position_pct",
                    "max_positions",
                    "max_sector_positions",
                    "max_sector_gross_pct",
                    "max_total_gross_pct",
                    "max_drawdown",
                    "daily_loss_limit",
                )
                if key in risk
            },
            stop_atr_multiple=float(execution.get("stop_atr_multiple", 1.5)),
            hedge=HedgeMode(hedge.get("mode", HedgeMode.NONE)),
            cost_multiplier=float(costs.get("multiplier", 1.0)),
        )

    @classmethod
    def from_yaml(cls, path: Path) -> StrategyConfig:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("strategy config must be a mapping")
        return cls.from_mapping(raw)

    @property
    def config_hash(self) -> str:
        encoded = json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class StrategyInput:
    symbol: str
    event_class: str
    event_confidence: float | None
    graph_exposure: float | None
    graph_confidence: float | None
    cause_score: float | None
    cause_direction: float | None
    observed_residual: float | None
    residual_z: float | None
    sector_residual_z: float | None
    volume_z: float | None
    response_state: str | None
    q10: float | None
    q50: float | None
    q90: float | None
    probability_positive: float | None
    horizon_days: int
    ood: bool = False
    market_fresh: bool = True
    event_timestamp_known: bool = True
    already_priced: bool | None = None
    portfolio_allows: bool = True


@dataclass(frozen=True)
class StrategyDecision:
    action: StrategyAction
    reason_codes: tuple[str, ...]
    score: float | None
    absorption_ratio: float | None
    direction: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


DEFAULT_STRATEGY_CONFIG = StrategyConfig()


def _missing(values: StrategyInput) -> list[str]:
    names = {
        "event_confidence": values.event_confidence,
        "graph_exposure": values.graph_exposure,
        "graph_confidence": values.graph_confidence,
        "q10": values.q10,
        "q50": values.q50,
        "q90": values.q90,
        "probability_positive": values.probability_positive,
        "observed_residual": values.observed_residual,
    }
    return [name for name, value in names.items() if value is None]


def decide(values: StrategyInput, config: StrategyConfig | None = None) -> StrategyDecision:
    """Evaluate the fixed policy from a single cutoff snapshot."""

    config = config or DEFAULT_STRATEGY_CONFIG

    missing = _missing(values)
    if missing:
        return StrategyDecision(StrategyAction.ABSTAIN, ("MISSING_INPUT", *missing), None, None)
    assert values.q10 is not None and values.q50 is not None and values.q90 is not None
    assert values.probability_positive is not None and values.event_confidence is not None
    assert values.graph_exposure is not None and values.graph_confidence is not None
    assert values.observed_residual is not None
    reasons: list[str] = []
    direction = 1 if values.q50 > 0 else -1 if values.q50 < 0 else 0
    width = values.q90 - values.q10
    expected = abs(values.q50)
    absorption_ratio = abs(values.observed_residual) / max(expected, 1e-9)
    underabsorbed = absorption_ratio <= config.max_absorption_ratio
    residual_z = abs(values.residual_z or 0.0)
    priced = (
        values.already_priced
        if values.already_priced is not None
        else residual_z >= config.already_priced_residual_z
    )
    score = (
        abs(values.graph_exposure)
        * values.event_confidence
        * max(values.probability_positive, 1 - values.probability_positive)
    )
    if values.ood:
        reasons.append("OOD")
    if not values.market_fresh:
        reasons.append("STALE_MARKET")
    if not values.event_timestamp_known:
        reasons.append("UNKNOWN_EVENT_TIME")
    if values.horizon_days not in {1, 2, 5} or values.horizon_days > config.max_horizon_days:
        reasons.append("HORIZON_NOT_TRADEABLE")
    if abs(values.graph_exposure) < config.min_graph_exposure:
        reasons.append("GRAPH_EXPOSURE_BELOW_THRESHOLD")
    if values.graph_confidence < config.min_graph_confidence:
        reasons.append("GRAPH_CONFIDENCE_BELOW_THRESHOLD")
    if values.event_confidence < config.min_event_confidence:
        reasons.append("EVENT_CONFIDENCE_BELOW_THRESHOLD")
    if expected < config.min_q50_abs:
        reasons.append("Q50_BELOW_THRESHOLD")
    if width > config.max_interval_width:
        reasons.append("INTERVAL_TOO_WIDE")
    if not underabsorbed:
        reasons.append("ABSORBED")
    if priced:
        reasons.append("ALREADY_PRICED")
    if not values.portfolio_allows:
        reasons.append("PORTFOLIO_LIMIT")
    probability_ok = (
        values.probability_positive >= config.min_probability
        if direction > 0
        else values.probability_positive <= 1 - config.min_probability
    )
    if not probability_ok:
        reasons.append("PROBABILITY_BELOW_THRESHOLD")
    compatible = (
        values.cause_direction is None
        or values.cause_direction == 0
        or values.cause_direction == direction
    )
    if not compatible:
        reasons.append("CAUSE_DIRECTION_MISMATCH")
    confirmation_ok = True
    if config.confirmation != ConfirmationMode.NONE:
        market_ok = (values.residual_z or 0.0) * direction >= 0
        sector_ok = (values.sector_residual_z or 0.0) * direction >= 0
        volume_ok = (values.volume_z or 0.0) >= (
            1.0 if config.confirmation == ConfirmationMode.STRICT else 0.0
        )
        confirmation_ok = (
            market_ok and sector_ok and volume_ok
            if config.confirmation == ConfirmationMode.STRICT
            else market_ok or sector_ok
        )
        if not confirmation_ok:
            reasons.append("MARKET_CONFIRMATION_MISSING")
    if reasons:
        return StrategyDecision(
            StrategyAction.ABSTAIN,
            tuple(reasons),
            score,
            absorption_ratio,
            direction,
            {"confirmation": confirmation_ok, "already_priced": priced},
        )
    action = StrategyAction.LONG if direction > 0 else StrategyAction.SHORT
    return StrategyDecision(
        action,
        ("SIGNAL_ACCEPTED",),
        score,
        absorption_ratio,
        direction,
        {"confirmation": confirmation_ok, "already_priced": priced},
    )
