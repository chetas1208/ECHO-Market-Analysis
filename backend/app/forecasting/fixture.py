"""Deterministic synthetic fixture generator used only by tests and local demos."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.forecasting.features import FEATURE_NAMES
from app.forecasting.types import FORECAST_HORIZONS


def fixture_rows() -> list[dict[str, object]]:
    symbols = ("NVDA", "AMD", "XOM")
    rows: list[dict[str, object]] = []
    start = datetime(2025, 1, 2, 14, 30, tzinfo=UTC)
    for event_index in range(15):
        event_id = f"fixture_event_{event_index:02d}"
        issuance = start + timedelta(days=event_index)
        for symbol_index, symbol in enumerate(symbols):
            exposure = ((symbol_index - 1) * 0.42) + ((event_index % 5) - 2) * 0.03
            features = {name: 0.0 for name in FEATURE_NAMES}
            features.update(
                {
                    "event_severity": 0.65 + (event_index % 3) * 0.08,
                    "event_novelty": 0.55 + (event_index % 4) * 0.06,
                    "event_corroboration": 0.7,
                    "event_confidence": 0.82,
                    "event_independent_sources": 3.0,
                    "event_age_hours": 0.5 + event_index * 0.01,
                    "economic_channel_count": 2.0,
                    "economic_channel_signed_strength": exposure,
                    "economic_channel_abs_strength": abs(exposure),
                    "graph_exposure": exposure,
                    "graph_confidence": 0.75,
                    "graph_path_depth": 2.0,
                    "graph_supporting_paths": 3.0,
                    "graph_strongest_path_weight": 0.7,
                    "graph_strongest_path_confidence": 0.8,
                    "graph_direct_company_mention": 1.0 if symbol_index == 0 else 0.0,
                    "cause_score": 0.7,
                    "cause_temporal_score": 0.8,
                    "cause_entity_score": 0.7,
                    "cause_economic_score": 0.75,
                    "cause_graph_score": 0.8,
                    "cause_market_score": 0.6,
                    "cause_source_score": 0.85,
                    "response_confirmed": 1.0 if event_index % 2 else 0.0,
                    "response_unconfirmed": 1.0 if event_index % 2 == 0 else 0.0,
                    "market_return_1m": 0.0005 * (event_index - 7),
                    "market_return_5m": 0.001 * (symbol_index - 1),
                    "market_return_15m": 0.0015 * (event_index % 3 - 1),
                    "market_return_z": (event_index % 5 - 2) * 0.4,
                    "market_volume_z": 1.0 + event_index % 3,
                    "market_volatility_z": 0.5 + event_index % 2,
                    "market_residual": exposure * 0.004,
                    "market_residual_z": exposure * 1.2,
                    "sector_residual": exposure * 0.003,
                    "sector_residual_z": exposure,
                    "absorption_residual": exposure * 0.004,
                    "absorption_volume": 1.0 + event_index % 3,
                }
            )
            targets = {
                horizon: exposure * (0.004 * days**0.5) + (event_index - 7) * 0.00015 * days
                for horizon, days in FORECAST_HORIZONS.items()
            }
            rows.append(
                {
                    "event_id": event_id,
                    "symbol": symbol,
                    "event_group": event_id,
                    "issuance_timestamp": issuance.isoformat(),
                    "data_cutoff_at": issuance.isoformat(),
                    "graph_snapshot_id": "fixture_graph_v1",
                    "feature_version": "echo-features-v1",
                    "features": features,
                    "targets": targets,
                }
            )
    return rows


def write_fixture(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in fixture_rows()) + "\n",
        encoding="utf-8",
    )
