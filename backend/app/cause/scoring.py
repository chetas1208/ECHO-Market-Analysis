"""Pure Cause Engine scoring functions."""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import UTC, datetime

from app.cause.types import CauseCandidateScore, CauseConfig, CauseStatus, ResponseState


def temporal_score(delta_seconds: float, tau_seconds: float) -> float:
    """Exponential non-negative temporal decay; the caller enforces the time window."""
    if delta_seconds < 0 or tau_seconds <= 0:
        return 0.0
    return math.exp(-delta_seconds / tau_seconds)


def direction_consistency(expected: float | str | None, observed: float | str | None) -> float:
    """Return +1 agreement, 0 ambiguity, or -1 directional disagreement."""

    def sign(value: float | str | None) -> int:
        if isinstance(value, str):
            normalized = value.casefold()
            if normalized in {"positive", "up", "+", "1"}:
                return 1
            if normalized in {"negative", "down", "-", "-1"}:
                return -1
            return 0
        if value is None or not math.isfinite(float(value)) or float(value) == 0:
            return 0
        return 1 if float(value) > 0 else -1

    expected_sign = sign(expected)
    observed_sign = sign(observed)
    if expected_sign == 0 or observed_sign == 0:
        return 0.0
    return 1.0 if expected_sign == observed_sign else -1.0


def weighted_cause_score(components: Mapping[str, float], config: CauseConfig) -> float:
    """Normalize configured weights and produce one bounded compatibility score."""
    total = sum(config.weights.values())
    score = sum(
        float(components.get(name, 0.0)) * weight / total for name, weight in config.weights.items()
    )
    return round(min(max(score, 0.0), 1.0), 6)


def classify_candidates(candidates: list[CauseCandidateScore], config: CauseConfig) -> CauseStatus:
    if not candidates or candidates[0].score < config.min_cause_score:
        return CauseStatus.UNKNOWN
    if len(candidates) > 1 and candidates[0].score - candidates[1].score <= config.ambiguity_margin:
        return CauseStatus.AMBIGUOUS
    return CauseStatus.IDENTIFIED


def response_state(
    exposure: float | None,
    residual_z: float | None,
    config: CauseConfig,
) -> ResponseState:
    """Classify observed residual against directional graph exposure."""
    if exposure is None or residual_z is None or not math.isfinite(residual_z):
        return ResponseState.NOT_OBSERVED
    if abs(exposure) < 0.02 or residual_z == 0:
        return ResponseState.UNCONFIRMED
    consistency = direction_consistency(exposure, residual_z)
    if consistency < 0:
        return ResponseState.OPPOSITE
    observed = min(abs(residual_z) / 3.0, 1.0)
    expected = min(abs(exposure), 1.0)
    if observed >= max(
        config.response_confirm_threshold, expected * config.response_overreaction_multiplier
    ):
        return ResponseState.OVERREACTING
    if observed >= max(config.response_confirm_threshold, expected * 0.75):
        return ResponseState.CONFIRMED
    if observed >= expected * 0.25:
        return ResponseState.PARTIAL
    return ResponseState.UNCONFIRMED


def event_time(event: object) -> datetime:
    timestamp = event.timestamp  # type: ignore[attr-defined]
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        return timestamp.replace(tzinfo=UTC)
    return timestamp.astimezone(UTC)
