"""Chronological, event-group-aware dataset splitting and train-only scaling."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np

from app.forecasting.types import DatasetRow, DatasetSplit


class DatasetIntegrityError(ValueError):
    """Raised when a training dataset violates its timestamp/group contract."""


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise DatasetIntegrityError("dataset timestamps must be timezone-aware")
    return value.astimezone(UTC)


def dataset_hash(rows: list[DatasetRow]) -> str:
    payload = [
        {
            "event_id": row.event_id,
            "symbol": row.symbol,
            "event_group": row.event_group,
            "issuance_timestamp": _utc(row.issuance_timestamp).isoformat(),
            "data_cutoff_at": _utc(row.data_cutoff_at).isoformat(),
            "graph_snapshot_id": row.graph_snapshot_id,
            "feature_version": row.feature_version,
            "features": row.features,
            "targets": row.targets,
        }
        for row in sorted(
            rows, key=lambda item: (item.issuance_timestamp, item.event_id, item.symbol)
        )
    ]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def validate_rows(rows: list[DatasetRow]) -> None:
    if not rows:
        raise DatasetIntegrityError("dataset is empty")
    for row in rows:
        issuance = _utc(row.issuance_timestamp)
        cutoff = _utc(row.data_cutoff_at)
        if cutoff > issuance:
            raise DatasetIntegrityError(f"feature cutoff is after issuance for {row.event_id}")
        if not row.event_id or not row.symbol or not row.event_group:
            raise DatasetIntegrityError("event_id, symbol, and event_group are required")
        for name, value in row.features.items():
            if value is not None and not math.isfinite(float(value)):
                raise DatasetIntegrityError(f"non-finite feature {name} in {row.event_id}")
        for horizon, value in row.targets.items():
            if not math.isfinite(float(value)):
                raise DatasetIntegrityError(f"non-finite target {horizon} in {row.event_id}")


def chronological_event_group_split(
    rows: list[DatasetRow], *, train_fraction: float = 0.6, validation_fraction: float = 0.2
) -> DatasetSplit:
    """Split whole event groups in chronological order; never random-shuffle rows."""

    validate_rows(rows)
    if not 0 < train_fraction < 1 or not 0 <= validation_fraction < 1:
        raise DatasetIntegrityError("split fractions are invalid")
    if train_fraction + validation_fraction >= 1:
        raise DatasetIntegrityError("train and validation fractions must leave a test period")
    groups: dict[str, datetime] = {}
    for row in rows:
        timestamp = _utc(row.issuance_timestamp)
        groups[row.event_group] = min(groups.get(row.event_group, timestamp), timestamp)
    ordered_groups = [
        group for group, _ in sorted(groups.items(), key=lambda item: (item[1], item[0]))
    ]
    count = len(ordered_groups)
    train_end = max(1, min(count - 2 if count >= 3 else count, math.floor(count * train_fraction)))
    validation_end = max(
        train_end, min(count - 1, train_end + math.floor(count * validation_fraction))
    )
    train_groups = set(ordered_groups[:train_end])
    validation_groups = set(ordered_groups[train_end:validation_end])
    test_groups = set(ordered_groups[validation_end:])
    if count >= 3 and (not validation_groups or not test_groups):
        train_end = max(1, count - 2)
        validation_groups = {ordered_groups[train_end]}
        test_groups = set(ordered_groups[train_end + 1 :])
    train = tuple(row for row in rows if row.event_group in train_groups)
    validation = tuple(row for row in rows if row.event_group in validation_groups)
    test = tuple(row for row in rows if row.event_group in test_groups)
    return DatasetSplit(
        train=train,
        validation=validation,
        test=test,
        diagnostics={
            "dataset_hash": dataset_hash(rows),
            "event_groups": count,
            "train_groups": sorted(train_groups),
            "validation_groups": sorted(validation_groups),
            "test_groups": sorted(test_groups),
            "train_start": min((_utc(row.issuance_timestamp) for row in train), default=None),
            "train_end": max((_utc(row.issuance_timestamp) for row in train), default=None),
            "validation_start": min(
                (_utc(row.issuance_timestamp) for row in validation), default=None
            ),
            "validation_end": max(
                (_utc(row.issuance_timestamp) for row in validation), default=None
            ),
            "test_start": min((_utc(row.issuance_timestamp) for row in test), default=None),
            "test_end": max((_utc(row.issuance_timestamp) for row in test), default=None),
        },
    )


@dataclass(frozen=True)
class TrainOnlyScaler:
    feature_names: tuple[str, ...]
    medians: tuple[float, ...]
    means: tuple[float, ...]
    scales: tuple[float, ...]

    @classmethod
    def fit(cls, rows: tuple[DatasetRow, ...], feature_names: tuple[str, ...]) -> TrainOnlyScaler:
        if not rows:
            raise DatasetIntegrityError("cannot fit scaler without training rows")
        matrix = np.array(
            [
                [
                    float(row.features[name]) if row.features.get(name) is not None else np.nan
                    for name in feature_names
                ]
                for row in rows
            ],
            dtype=float,
        )
        medians = np.nanmedian(matrix, axis=0)
        medians = np.where(np.isfinite(medians), medians, 0.0)
        filled = np.where(np.isfinite(matrix), matrix, medians)
        means = filled.mean(axis=0)
        scales = filled.std(axis=0, ddof=0)
        scales = np.where(scales > 1e-12, scales, 1.0)
        return cls(tuple(feature_names), tuple(medians), tuple(means), tuple(scales))

    def transform(self, features: dict[str, float | None]) -> np.ndarray:
        values = np.array(
            [
                float(features[name]) if features.get(name) is not None else median
                for name, median in zip(self.feature_names, self.medians, strict=True)
            ],
            dtype=float,
        )
        return (values - np.array(self.means)) / np.array(self.scales)
