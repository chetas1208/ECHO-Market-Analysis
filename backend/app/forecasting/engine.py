"""Forecast fusion, abstention, OOD checks, and horizon recommendation."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.forecasting.calibration import ConformalCalibrator, IsotonicCalibrator
from app.forecasting.models import QuantileModelSet, quantile_probability
from app.forecasting.types import (
    FORECAST_HORIZONS,
    ForecastAvailability,
    ForecastHorizon,
    ForecastResult,
    OODStatus,
)
from app.forecasting.volatility import HARForecast


@dataclass(frozen=True)
class OODReport:
    status: OODStatus
    distance: float | None
    missing_features: tuple[str, ...]


@dataclass
class ForecastArtifactBundle:
    model_version: str
    feature_version: str
    feature_names: tuple[str, ...]
    dataset_hash: str
    training_cutoff: datetime | None
    models: dict[str, QuantileModelSet]
    conformal: dict[str, ConformalCalibrator]
    probability: dict[str, IsotonicCalibrator]
    feature_min: dict[str, float]
    feature_max: dict[str, float]
    backend: str
    artifact_hash: str

    @classmethod
    def load(cls, path: Path) -> ForecastArtifactBundle:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("artifact_type") != "echo_forecast_bundle_v1":
            raise ValueError("unsupported forecast artifact")
        # Current local artifacts are linear fallback artifacts. LightGBM adapters remain
        # available to the trainer, but are intentionally not silently serialized as linear.
        import numpy as np

        from app.forecasting.models import LightGBMQuantileModel, LinearQuantileModel
        from app.forecasting.split import TrainOnlyScaler

        models: dict[str, QuantileModelSet] = {}
        for horizon, model_payload in payload["models"].items():
            quantiles: dict[str, LinearQuantileModel] = {}
            for name, item in model_payload["quantiles"].items():
                scaler = TrainOnlyScaler(
                    tuple(item["feature_names"]),
                    tuple(item["medians"]),
                    tuple(item["means"]),
                    tuple(item["scales"]),
                )
                if item["kind"] == "lightgbm_quantile":
                    try:
                        import lightgbm
                    except ImportError as exc:
                        raise ValueError("LightGBM artifact requires the lightgbm package") from exc
                    quantiles[name] = LightGBMQuantileModel(
                        model=lightgbm.Booster(model_str=item["model_str"]),
                        alpha=float(item["alpha"]),
                        feature_names=tuple(item["feature_names"]),
                        scaler=scaler,
                    )
                else:
                    quantiles[name] = LinearQuantileModel(
                        alpha=float(item["alpha"]),
                        feature_names=tuple(item["feature_names"]),
                        scaler=scaler,
                        weights=np.asarray(item["weights"], dtype=float),
                        intercept=float(item["intercept"]),
                        iterations=int(item.get("iterations", 350)),
                    )
            models[horizon] = QuantileModelSet(horizon, quantiles, model_payload["backend"])
        return cls(
            model_version=payload["model_version"],
            feature_version=payload["feature_version"],
            feature_names=tuple(payload["feature_names"]),
            dataset_hash=payload["dataset_hash"],
            training_cutoff=datetime.fromisoformat(payload["training_cutoff"])
            if payload.get("training_cutoff")
            else None,
            models=models,
            conformal={
                horizon: ConformalCalibrator(**item)
                for horizon, item in payload["conformal"].items()
            },
            probability={
                horizon: IsotonicCalibrator(tuple(item["x"]), tuple(item["y"]))
                for horizon, item in payload["probability"].items()
            },
            feature_min={name: float(value) for name, value in payload["feature_min"].items()},
            feature_max={name: float(value) for name, value in payload["feature_max"].items()},
            backend=payload["backend"],
            artifact_hash=payload["artifact_hash"],
        )


def check_ood(features: dict[str, float | None], bundle: ForecastArtifactBundle) -> OODReport:
    missing = tuple(name for name in bundle.feature_names if features.get(name) is None)
    if missing and len(missing) > max(2, len(bundle.feature_names) // 3):
        return OODReport(OODStatus.UNKNOWN, None, missing)
    distances: list[float] = []
    for name in bundle.feature_names:
        value = features.get(name)
        if value is None:
            continue
        lower = bundle.feature_min.get(name)
        upper = bundle.feature_max.get(name)
        if lower is None or upper is None:
            continue
        span = max(upper - lower, 1e-9)
        if value < lower:
            distances.append((lower - value) / span)
        elif value > upper:
            distances.append((value - upper) / span)
        else:
            distances.append(0.0)
    distance = max(distances, default=None)
    return OODReport(
        OODStatus.OOD if distance is not None and distance > 2.0 else OODStatus.IN_DISTRIBUTION,
        distance,
        missing,
    )


def recommend_horizon(
    horizons: dict[str, ForecastHorizon], *, transaction_cost: float = 0.0005
) -> str | None:
    usable = [item for item in horizons.values() if item.score is not None]
    if not usable:
        return None
    return max(
        usable, key=lambda item: (float(item.score), -item.trading_days, item.horizon)
    ).horizon


def estimate_information_half_life(decay_observations: list[tuple[float, float]]) -> float | None:
    """Estimate ln(2)/lambda from positive impact observations; no precision is invented."""

    usable = [
        (float(day), float(abs(impact)))
        for day, impact in decay_observations
        if day > 0 and impact > 0
    ]
    if len(usable) < 3:
        return None
    xs = [day for day, _ in usable]
    ys = [math.log(impact) for _, impact in usable]
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    denominator = sum((value - mean_x) ** 2 for value in xs)
    if denominator <= 0:
        return None
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True)) / denominator
    if slope >= 0:
        return None
    return round(math.log(2) / -slope, 4)


def generate_forecast(
    *,
    event_id: str,
    symbol: str,
    issued_at: datetime,
    data_cutoff_at: datetime,
    graph_snapshot_id: str | None,
    features: dict[str, float | None],
    bundle: ForecastArtifactBundle,
    volatility: dict[str, HARForecast],
    target_timestamps: dict[str, datetime],
    event_confidence: float | None = None,
    half_life: float | None = None,
) -> ForecastResult:
    feature_hash = ForecastResult.hash_features(features)
    ood = check_ood(features, bundle)
    if ood.status == OODStatus.OOD:
        return ForecastResult(
            event_id,
            symbol,
            issued_at,
            data_cutoff_at,
            graph_snapshot_id,
            bundle.model_version,
            bundle.feature_version,
            feature_hash,
            {},
            None,
            half_life,
            ForecastAvailability.FORECAST_UNAVAILABLE,
            {
                "ood": ood.status.value,
                "ood_distance": ood.distance,
                "missing_features": list(ood.missing_features),
                "artifact_hash": bundle.artifact_hash,
                "feature_snapshot": features,
            },
            "out_of_distribution_features",
        )
    horizons: dict[str, ForecastHorizon] = {}
    for horizon, days in FORECAST_HORIZONS.items():
        model = bundle.models.get(horizon)
        if model is None or horizon not in target_timestamps:
            continue
        raw = model.predict(features)
        q10, q50, q90 = bundle.conformal.get(horizon, ConformalCalibrator(0.0)).apply(
            raw["q10"], raw["q50"], raw["q90"]
        )
        raw_probability = quantile_probability(q10, q50, q90)
        probability = bundle.probability.get(horizon, IsotonicCalibrator((), ())).apply(
            raw_probability
        )
        risk = volatility.get(horizon, HARForecast(None, "VOLATILITY_UNAVAILABLE", 0)).volatility
        risk = risk if risk is not None and risk > 0 else max((q90 - q10) / 2.563, 1e-6)
        confidence = min(
            max(float(event_confidence) if event_confidence is not None else 0.5, 0.0), 1.0
        )
        score = abs(q50) / risk * confidence - 0.0005 * days
        horizons[horizon] = ForecastHorizon(
            horizon,
            days,
            target_timestamps[horizon],
            q10,
            q50,
            q90,
            probability,
            risk,
            confidence,
            score,
        )
    if not horizons:
        return ForecastResult(
            event_id,
            symbol,
            issued_at,
            data_cutoff_at,
            graph_snapshot_id,
            bundle.model_version,
            bundle.feature_version,
            feature_hash,
            {},
            None,
            half_life,
            ForecastAvailability.FORECAST_UNAVAILABLE,
            {"ood": ood.status.value, "missing_features": list(ood.missing_features)},
            "insufficient_horizon_data",
        )
    return ForecastResult(
        event_id,
        symbol,
        issued_at,
        data_cutoff_at,
        graph_snapshot_id,
        bundle.model_version,
        bundle.feature_version,
        feature_hash,
        horizons,
        recommend_horizon(horizons),
        half_life,
        ForecastAvailability.READY,
        {
            "ood": ood.status.value,
            "ood_distance": ood.distance,
            "missing_features": list(ood.missing_features),
            "backend": bundle.backend,
            "artifact_hash": bundle.artifact_hash,
            "feature_snapshot": features,
        },
    )
