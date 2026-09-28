"""Reproducible dataset, training, and evaluation helpers for the CLI."""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.forecasting.calibration import ConformalCalibrator, IsotonicCalibrator
from app.forecasting.models import QuantileModelSet
from app.forecasting.split import chronological_event_group_split, dataset_hash
from app.forecasting.types import FORECAST_HORIZONS, DatasetRow


def _datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("dataset timestamp must be timezone-aware")
    return parsed.astimezone(UTC)


def load_rows(path: Path) -> list[DatasetRow]:
    rows: list[DatasetRow] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
            rows.append(
                DatasetRow(
                    event_id=str(value["event_id"]),
                    symbol=str(value["symbol"]).upper(),
                    event_group=str(value.get("event_group", value["event_id"])),
                    issuance_timestamp=_datetime(value["issuance_timestamp"]),
                    data_cutoff_at=_datetime(value["data_cutoff_at"]),
                    graph_snapshot_id=value.get("graph_snapshot_id"),
                    feature_version=str(value.get("feature_version", "echo-features-v1")),
                    features={
                        name: (None if item is None else float(item))
                        for name, item in value["features"].items()
                    },
                    targets={name: float(item) for name, item in value["targets"].items()},
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid dataset row {line_number}: {exc}") from exc
    return rows


def _pinball(actual: list[float], predicted: list[float], alpha: float) -> float | None:
    if not actual:
        return None
    return sum(
        alpha * (y - p) if y >= p else (alpha - 1) * (y - p)
        for y, p in zip(actual, predicted, strict=True)
    ) / len(actual)


def _metrics(actual: list[float], predicted: list[float]) -> dict[str, float | None]:
    if not actual:
        return {"mae": None, "rmse": None, "directional_accuracy": None, "spearman": None}
    errors = [p - y for y, p in zip(actual, predicted, strict=True)]
    directional = sum(
        (y == 0 and p == 0) or (y > 0 and p > 0) or (y < 0 and p < 0)
        for y, p in zip(actual, predicted, strict=True)
    ) / len(actual)
    ranks_actual = {value: index for index, value in enumerate(sorted(actual))}
    ranks_predicted = {value: index for index, value in enumerate(sorted(predicted))}
    xa = [ranks_actual[value] for value in actual]
    xp = [ranks_predicted[value] for value in predicted]
    mean_a = sum(xa) / len(xa)
    mean_p = sum(xp) / len(xp)
    denominator = math.sqrt(
        sum((value - mean_a) ** 2 for value in xa) * sum((value - mean_p) ** 2 for value in xp)
    )
    return {
        "mae": sum(abs(error) for error in errors) / len(errors),
        "rmse": math.sqrt(sum(error * error for error in errors) / len(errors)),
        "directional_accuracy": directional,
        "spearman": sum((a - mean_a) * (p - mean_p) for a, p in zip(xa, xp, strict=True))
        / denominator
        if denominator
        else None,
    }


def _coverage(actual: list[float], lower: list[float], upper: list[float]) -> float | None:
    if not actual:
        return None
    return sum(
        low <= value <= high for value, low, high in zip(actual, lower, upper, strict=True)
    ) / len(actual)


def _serialize_model_set(model_set: QuantileModelSet) -> dict[str, Any]:
    quantiles: dict[str, Any] = {}
    for name, model in model_set.models.items():
        if not hasattr(model, "to_dict"):
            raise ValueError("LightGBM artifact serialization is unavailable in this build")
        quantiles[name] = model.to_dict()
    return {"backend": model_set.backend, "quantiles": quantiles}


def train_bundle(
    rows: list[DatasetRow],
    output: Path,
    *,
    backend: str = "auto",
    training_cutoff: datetime | None = None,
) -> dict[str, Any]:
    split = chronological_event_group_split(rows)
    feature_names = tuple(sorted({name for row in rows for name in row.features}))
    models: dict[str, QuantileModelSet] = {}
    conformal: dict[str, ConformalCalibrator] = {}
    probability: dict[str, IsotonicCalibrator] = {}
    horizon_metrics: dict[str, Any] = {}
    baseline_metrics: dict[str, Any] = {}
    ablation_metrics: dict[str, Any] = {}
    for horizon in FORECAST_HORIZONS:
        model_set = QuantileModelSet.fit(split.train, feature_names, horizon, backend=backend)
        models[horizon] = model_set
        validation = [row for row in split.validation if horizon in row.targets]
        raw_predictions = [model_set.predict(row.features) for row in validation]
        residuals = [
            row.targets[horizon] - prediction["q50"]
            for row, prediction in zip(validation, raw_predictions, strict=True)
        ]
        conformal[horizon] = ConformalCalibrator.fit(residuals)
        raw_probabilities = [
            0.5
            if prediction["q10"] <= 0 <= prediction["q90"]
            else (0.95 if prediction["q10"] > 0 else 0.05)
            for prediction in raw_predictions
        ]
        probability[horizon] = IsotonicCalibrator.fit(
            raw_probabilities, [row.targets[horizon] > 0 for row in validation]
        )
        test = [row for row in split.test if horizon in row.targets]
        predictions = [model_set.predict(row.features) for row in test]
        lower = [conformal[horizon].apply(p["q10"], p["q50"], p["q90"])[0] for p in predictions]
        median = [conformal[horizon].apply(p["q10"], p["q50"], p["q90"])[1] for p in predictions]
        upper = [conformal[horizon].apply(p["q10"], p["q50"], p["q90"])[2] for p in predictions]
        actual = [row.targets[horizon] for row in test]
        horizon_metrics[horizon] = {
            "test_rows": len(test),
            "mae": _metrics(actual, median)["mae"],
            "rmse": _metrics(actual, median)["rmse"],
            "directional_accuracy": _metrics(actual, median)["directional_accuracy"],
            "pinball_q10": _pinball(actual, lower, 0.1),
            "pinball_q50": _pinball(actual, median, 0.5),
            "pinball_q90": _pinball(actual, upper, 0.9),
            "coverage_80": _coverage(actual, lower, upper),
            "interval_width": sum(high - low for low, high in zip(lower, upper, strict=True))
            / len(actual)
            if actual
            else None,
        }
        train_targets = [row.targets[horizon] for row in split.train if horizon in row.targets]
        historical_mean = sum(train_targets) / len(train_targets) if train_targets else 0.0
        exposure_predictions = [
            0.01 * float(row.features.get("graph_exposure") or 0.0) for row in test
        ]
        baseline_metrics[horizon] = {
            "zero": _metrics(actual, [0.0 for _ in actual]),
            "historical_mean": _metrics(actual, [historical_mean for _ in actual]),
            "exposure_only": _metrics(actual, exposure_predictions),
            "chronos_only": {"status": "BASELINE_UNAVAILABLE"},
            "selected_model": _metrics(actual, median),
        }
    ablation_groups = {
        "without_graph": lambda name: not name.startswith("graph_"),
        "without_event": lambda name: (
            not name.startswith("event_") and not name.startswith("economic_")
        ),
        "without_absorption": lambda name: (
            not name.startswith("absorption_")
            and name
            not in {
                "market_residual",
                "market_residual_z",
                "market_volume_z",
                "market_volatility_z",
            }
        ),
        "without_cause": lambda name: (
            not name.startswith("cause_") and not name.startswith("response_")
        ),
    }
    for ablation, include in ablation_groups.items():
        reduced_names = tuple(name for name in feature_names if include(name))
        ablation_metrics[ablation] = {}
        for horizon in FORECAST_HORIZONS:
            try:
                reduced_model = QuantileModelSet.fit(
                    split.train, reduced_names, horizon, backend="linear"
                )
            except Exception as exc:
                ablation_metrics[ablation][horizon] = {
                    "status": "UNAVAILABLE",
                    "reason": str(exc),
                }
                continue
            test = [row for row in split.test if horizon in row.targets]
            actual = [row.targets[horizon] for row in test]
            median = [reduced_model.predict(row.features)["q50"] for row in test]
            ablation_metrics[ablation][horizon] = _metrics(actual, median)
    feature_min: dict[str, float] = {}
    feature_max: dict[str, float] = {}
    for name in feature_names:
        values = [
            float(row.features[name]) for row in split.train if row.features.get(name) is not None
        ]
        if values:
            feature_min[name] = min(values)
            feature_max[name] = max(values)
    model_version = f"echo-forecast-v1-{dataset_hash(rows)[:12]}"
    bundle_payload: dict[str, Any] = {
        "artifact_type": "echo_forecast_bundle_v1",
        "model_version": model_version,
        "feature_version": rows[0].feature_version,
        "feature_names": list(feature_names),
        "dataset_hash": dataset_hash(rows),
        "training_cutoff": (
            training_cutoff or max(row.issuance_timestamp for row in split.train)
        ).isoformat(),
        "models": {
            horizon: _serialize_model_set(model_set) for horizon, model_set in models.items()
        },
        "conformal": {
            horizon: {"adjustment": item.adjustment, "nominal_coverage": item.nominal_coverage}
            for horizon, item in conformal.items()
        },
        "probability": {
            horizon: {"x": list(item.x), "y": list(item.y)} for horizon, item in probability.items()
        },
        "feature_min": feature_min,
        "feature_max": feature_max,
        "backend": ",".join(sorted({model_set.backend for model_set in models.values()})),
    }
    canonical = json.dumps(
        bundle_payload, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    import hashlib

    bundle_payload["artifact_hash"] = hashlib.sha256(canonical).hexdigest()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(bundle_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report = {
        "status": "complete" if split.test else "insufficient_test_data",
        "dataset": {
            "rows": len(rows),
            "events": len({row.event_id for row in rows}),
            "symbols": sorted({row.symbol for row in rows}),
            "date_start": min(row.issuance_timestamp for row in rows).isoformat(),
            "date_end": max(row.issuance_timestamp for row in rows).isoformat(),
            "dataset_hash": dataset_hash(rows),
        },
        "split": split.diagnostics,
        "model": {
            "version": model_version,
            "backend": bundle_payload["backend"],
            "artifact_hash": bundle_payload["artifact_hash"],
        },
        "metrics": horizon_metrics,
        "baselines": baseline_metrics,
        "ablations": ablation_metrics,
        "target_distributions": {
            horizon: {
                "count": len([row for row in rows if horizon in row.targets]),
                "min": min(
                    (row.targets[horizon] for row in rows if horizon in row.targets),
                    default=None,
                ),
                "max": max(
                    (row.targets[horizon] for row in rows if horizon in row.targets),
                    default=None,
                ),
                "mean": (
                    sum(row.targets[horizon] for row in rows if horizon in row.targets)
                    / max(1, len([row for row in rows if horizon in row.targets]))
                ),
            }
            for horizon in FORECAST_HORIZONS
        },
        "leakage": {
            "chronological": True,
            "event_group_aware": True,
            "scaler_fit": "train_only",
            "calibration_fit": "validation_only",
        },
        "chronos": {"status": "BASELINE_UNAVAILABLE", "model": "amazon/chronos-2"},
    }
    return report


def write_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    markdown = [
        "# Day 6 Forecast Evaluation",
        "",
        f"Status: **{report['status']}**",
        "",
        "```json",
        json.dumps(report, indent=2, sort_keys=True, default=str),
        "```",
        "",
    ]
    path.with_suffix(".md").write_text("\n".join(markdown), encoding="utf-8")
