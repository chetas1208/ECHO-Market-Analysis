"""Market shock detector: score -> gate (ready, level, bar dedupe, cooldown) -> emit decision.

Deterministic: no wall clock. Time comes only from ``SymbolFeatures.as_of``.
Reasons are stable strings: not_ready, below_threshold, no_direction, cooldown, duplicate_bar, emit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.market.settings import ShockConfig
from app.market.shock.cooldown import ShockCooldown
from app.market.shock.score import assess
from app.market.types import ShockAssessment, ShockLevel, SymbolFeatures

REASON_NOT_READY = "not_ready"
REASON_BELOW_THRESHOLD = "below_threshold"
REASON_NO_DIRECTION = "no_direction"
REASON_COOLDOWN = "cooldown"
REASON_DUPLICATE_BAR = "duplicate_bar"
REASON_EMIT = "emit"

_EMITTABLE = (ShockLevel.SHOCK, ShockLevel.SEVERE)


@dataclass(frozen=True)
class ShockDecision:
    emit: bool
    assessment: ShockAssessment
    reason: str


@dataclass
class DetectorStats:
    evaluated: int = 0
    emitted: int = 0
    suppressed_cooldown: int = 0
    duplicates: int = 0
    not_ready: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "evaluated": self.evaluated,
            "emitted": self.emitted,
            "suppressed_cooldown": self.suppressed_cooldown,
            "duplicates": self.duplicates,
            "not_ready": self.not_ready,
        }


@dataclass
class MarketShockDetector:
    cfg: ShockConfig
    cooldown: ShockCooldown = field(init=False)
    stats: DetectorStats = field(default_factory=DetectorStats, init=False)
    _last_as_of: dict[str, datetime] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        self.cooldown = ShockCooldown(self.cfg.cooldown_seconds)

    def evaluate(self, features: SymbolFeatures) -> ShockDecision:
        assessment = assess(features, self.cfg)
        last = self._last_as_of.get(features.symbol)
        if last is not None and features.as_of <= last:
            self.stats.duplicates += 1
            return ShockDecision(False, assessment, REASON_DUPLICATE_BAR)

        self._last_as_of[features.symbol] = features.as_of
        self.stats.evaluated += 1

        if not assessment.ready:
            self.stats.not_ready += 1
            return ShockDecision(False, assessment, REASON_NOT_READY)
        if assessment.level not in _EMITTABLE:
            return ShockDecision(False, assessment, REASON_BELOW_THRESHOLD)
        if assessment.direction is None:
            return ShockDecision(False, assessment, REASON_NO_DIRECTION)
        if not self.cooldown.should_emit(
            features.symbol, assessment.direction, assessment.level, features.as_of
        ):
            self.stats.suppressed_cooldown += 1
            return ShockDecision(False, assessment, REASON_COOLDOWN)

        self.stats.emitted += 1
        return ShockDecision(True, assessment, REASON_EMIT)

    def reset(self) -> None:
        self.cooldown.reset()
        self._last_as_of.clear()
        self.stats = DetectorStats()
