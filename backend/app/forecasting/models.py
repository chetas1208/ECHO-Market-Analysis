"""Small deterministic quantile model adapters.

LightGBM is optional so the API can remain local and honest on a clean install. When it
is unavailable, the training command uses a deterministic linear pinball model and records
that fallback explicitly; it never labels the fallback as LightGBM.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from app.forecasting.split import TrainOnlyScaler
from app.forecasting.types import DatasetRow


class QuantileModelError(RuntimeError):
    """Raised when a quantile model cannot train or predict."""


def quantile_probability(q10: float, q50: float, q90: float) -> float:
    """Approximate P(Y > 0) from a monotonic piecewise-linear quantile CDF."""

    q10, q50, q90 = sorted((float(q10), float(q50), float(q90)))
    if q10 >= 0:
        return 0.95
    if q90 <= 0:
        return 0.05
    if q50 >= 0:
        return float(0.5 + 0.4 * min(max((q50 - 0.0) / max(q50 - q10, 1e-12), 0.0), 1.0))
    return float(0.1 + 0.4 * min(max((0.0 - q10) / max(q90 - q10, 1e-12), 0.0), 1.0))


def monotonic_quantiles(values: dict[str, float]) -> tuple[float, float, float]:
    ordered = sorted((float(values["q10"]), float(values["q50"]), float(values["q90"])))
    return tuple(ordered)  # type: ignore[return-value]


@dataclass
class LinearQuantileModel:
    alpha: float
    feature_names: tuple[str, ...]
    scaler: TrainOnlyScaler
    weights: np.ndarray
    intercept: float
    iterations: int = 350
    learning_rate: float = 0.025

    @classmethod
    def fit(
        cls,
        rows: tuple[DatasetRow, ...],
        feature_names: tuple[str, ...],
        horizon: str,
        alpha: float,
        *,
        iterations: int = 350,
    ) -> LinearQuantileModel:
        usable = tuple(row for row in rows if horizon in row.targets)
        if len(usable) < 2:
            raise QuantileModelError(f"insufficient rows for {horizon} q{alpha}")
        scaler = TrainOnlyScaler.fit(usable, feature_names)
        matrix = np.vstack([scaler.transform(row.features) for row in usable])
        target = np.array([float(row.targets[horizon]) for row in usable], dtype=float)
        weights = np.zeros(matrix.shape[1], dtype=float)
        intercept = float(np.quantile(target, alpha))
        for _ in range(iterations):
            residual = target - (intercept + matrix @ weights)
            gradient = np.where(residual >= 0.0, -alpha, 1.0 - alpha)
            intercept -= 0.025 * float(gradient.mean())
            weights -= 0.025 * (matrix.T @ gradient / len(usable) + 0.01 * weights)
        return cls(alpha, tuple(feature_names), scaler, weights, intercept, iterations)

    def predict(self, features: dict[str, float | None]) -> float:
        value = self.intercept + float(self.scaler.transform(features) @ self.weights)
        return value if math.isfinite(value) else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "linear_pinball",
            "alpha": self.alpha,
            "feature_names": list(self.feature_names),
            "medians": list(self.scaler.medians),
            "means": list(self.scaler.means),
            "scales": list(self.scaler.scales),
            "weights": self.weights.tolist(),
            "intercept": self.intercept,
            "iterations": self.iterations,
            "learning_rate": self.learning_rate,
        }


@dataclass
class LightGBMQuantileModel:
    model: Any
    alpha: float
    feature_names: tuple[str, ...]
    scaler: TrainOnlyScaler

    @classmethod
    def fit(
        cls,
        rows: tuple[DatasetRow, ...],
        feature_names: tuple[str, ...],
        horizon: str,
        alpha: float,
    ) -> LightGBMQuantileModel:
        try:
            from lightgbm import LGBMRegressor
        except ImportError as exc:
            raise QuantileModelError("LightGBM is not installed") from exc
        usable = tuple(row for row in rows if horizon in row.targets)
        if len(usable) < 8:
            raise QuantileModelError(f"insufficient rows for LightGBM {horizon} q{alpha}")
        scaler = TrainOnlyScaler.fit(usable, feature_names)
        matrix = np.vstack([scaler.transform(row.features) for row in usable])
        target = np.array([float(row.targets[horizon]) for row in usable], dtype=float)
        model = LGBMRegressor(
            objective="quantile",
            alpha=alpha,
            n_estimators=100,
            learning_rate=0.04,
            num_leaves=15,
            min_child_samples=5,
            reg_alpha=0.1,
            reg_lambda=1.0,
            random_state=17,
            verbosity=-1,
        )
        model.fit(matrix, target)
        return cls(model, alpha, tuple(feature_names), scaler)

    def predict(self, features: dict[str, float | None]) -> float:
        value = float(self.model.predict(self.scaler.transform(features).reshape(1, -1))[0])
        return value if math.isfinite(value) else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "lightgbm_quantile",
            "alpha": self.alpha,
            "feature_names": list(self.feature_names),
            "medians": list(self.scaler.medians),
            "means": list(self.scaler.means),
            "scales": list(self.scaler.scales),
            "model_str": self.model.booster_.model_to_string(),
        }


@dataclass
class QuantileModelSet:
    horizon: str
    models: dict[str, LinearQuantileModel | LightGBMQuantileModel]
    backend: str

    @classmethod
    def fit(
        cls,
        rows: tuple[DatasetRow, ...],
        feature_names: tuple[str, ...],
        horizon: str,
        *,
        backend: str = "auto",
    ) -> QuantileModelSet:
        models: dict[str, LinearQuantileModel | LightGBMQuantileModel] = {}
        resolved = backend
        for name, alpha in (("q10", 0.1), ("q50", 0.5), ("q90", 0.9)):
            if backend in {"auto", "lightgbm"}:
                try:
                    models[name] = LightGBMQuantileModel.fit(rows, feature_names, horizon, alpha)
                    resolved = "lightgbm"
                    continue
                except QuantileModelError:
                    if backend == "lightgbm":
                        raise
            models[name] = LinearQuantileModel.fit(rows, feature_names, horizon, alpha)
            resolved = "linear_pinball_fallback"
        return cls(horizon, models, resolved)

    def predict(self, features: dict[str, float | None]) -> dict[str, float]:
        raw = {name: model.predict(features) for name, model in self.models.items()}
        q10, q50, q90 = monotonic_quantiles(raw)
        return {"q10": q10, "q50": q50, "q90": q90}
