"""Lightweight HAR-RV volatility context model."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class HARForecast:
    volatility: float | None
    status: str
    observations: int


@dataclass
class HARVolatilityModel:
    coefficients: tuple[float, float, float, float] | None = None
    min_observations: int = 22

    def fit_predict(self, returns: list[float], horizon_days: int = 1) -> HARForecast:
        values = np.asarray(
            [float(value) for value in returns if math.isfinite(float(value))], dtype=float
        )
        if len(values) < self.min_observations:
            return HARForecast(None, "VOLATILITY_UNAVAILABLE", len(values))
        daily = values * values
        rows: list[list[float]] = []
        target: list[float] = []
        for index in range(22, len(daily)):
            rows.append(
                [
                    1.0,
                    float(daily[index - 1]),
                    float(daily[index - 5 : index].mean()),
                    float(daily[index - 22 : index].mean()),
                ]
            )
            target.append(float(daily[index]))
        if len(rows) < 3:
            return HARForecast(None, "VOLATILITY_UNAVAILABLE", len(values))
        matrix = np.asarray(rows, dtype=float)
        coefficients, *_ = np.linalg.lstsq(matrix, np.asarray(target, dtype=float), rcond=None)
        self.coefficients = tuple(float(value) for value in coefficients)
        latest = np.asarray(
            [
                1.0,
                float(daily[-1]),
                float(daily[-5:].mean()),
                float(daily[-22:].mean()),
            ]
        )
        forecast_variance = max(0.0, float(latest @ coefficients)) * max(1, horizon_days)
        return HARForecast(math.sqrt(forecast_variance), "READY", len(values))
