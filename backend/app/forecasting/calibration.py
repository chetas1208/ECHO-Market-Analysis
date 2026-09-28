"""Validation-only conformal intervals and probability calibration."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class ConformalCalibrator:
    """Symmetric absolute-residual adjustment fitted on validation rows only."""

    adjustment: float
    nominal_coverage: float = 0.8

    @classmethod
    def fit(cls, residuals: list[float], nominal_coverage: float = 0.8) -> ConformalCalibrator:
        if not residuals:
            return cls(0.0, nominal_coverage)
        if not 0 < nominal_coverage < 1:
            raise ValueError("nominal coverage must be between zero and one")
        values = np.sort(np.abs(np.asarray(residuals, dtype=float)))
        index = min(len(values) - 1, max(0, math.ceil((len(values) + 1) * nominal_coverage) - 1))
        return cls(float(values[index]), nominal_coverage)

    def apply(self, q10: float, q50: float, q90: float) -> tuple[float, float, float]:
        q10, q50, q90 = sorted((float(q10), float(q50), float(q90)))
        return q10 - self.adjustment, q50, q90 + self.adjustment


@dataclass(frozen=True)
class IsotonicCalibrator:
    """Monotonic piecewise-constant calibration fitted only on validation data."""

    x: tuple[float, ...]
    y: tuple[float, ...]

    @classmethod
    def fit(cls, raw: list[float], observed_positive: list[bool]) -> IsotonicCalibrator:
        if len(raw) != len(observed_positive) or not raw:
            return cls((), ())
        pairs = sorted(
            (min(max(float(value), 0.0), 1.0), float(flag))
            for value, flag in zip(raw, observed_positive, strict=True)
        )
        blocks: list[list[float]] = []
        for x_value, y_value in pairs:
            blocks.append([x_value, y_value, 1.0])
            while len(blocks) >= 2 and blocks[-2][1] > blocks[-1][1]:
                left, right = blocks[-2], blocks[-1]
                total = left[2] + right[2]
                blocks[-2] = [
                    (left[0] * left[2] + right[0] * right[2]) / total,
                    (left[1] * left[2] + right[1] * right[2]) / total,
                    total,
                ]
                blocks.pop()
        return cls(tuple(block[0] for block in blocks), tuple(block[1] for block in blocks))

    def apply(self, value: float) -> float:
        if not self.x:
            return min(max(float(value), 0.0), 1.0)
        value = min(max(float(value), 0.0), 1.0)
        index = min(range(len(self.x)), key=lambda position: abs(self.x[position] - value))
        return min(max(self.y[index], 0.0), 1.0)
