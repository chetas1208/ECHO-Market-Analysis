"""Cutoff-bound event, graph, cause, market, and absorption features."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

from app.market.types import Bar

FEATURE_VERSION = "echo-features-v1"

FEATURE_NAMES = (
    "event_severity",
    "event_novelty",
    "event_corroboration",
    "event_confidence",
    "event_independent_sources",
    "event_age_hours",
    "economic_channel_count",
    "economic_channel_signed_strength",
    "economic_channel_abs_strength",
    "graph_exposure",
    "graph_confidence",
    "graph_path_depth",
    "graph_supporting_paths",
    "graph_strongest_path_weight",
    "graph_strongest_path_confidence",
    "graph_direct_company_mention",
    "cause_score",
    "cause_temporal_score",
    "cause_entity_score",
    "cause_economic_score",
    "cause_graph_score",
    "cause_market_score",
    "cause_source_score",
    "response_not_observed",
    "response_opposite",
    "response_unconfirmed",
    "response_partial",
    "response_confirmed",
    "response_overreacting",
    "market_return_1m",
    "market_return_5m",
    "market_return_15m",
    "market_return_z",
    "market_volume_z",
    "market_volatility_z",
    "market_residual",
    "market_residual_z",
    "sector_residual",
    "sector_residual_z",
    "absorption_residual",
    "absorption_volume",
)


class FeatureLeakageError(ValueError):
    """Raised when a future observation is supplied to a cutoff-bound feature build."""


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise FeatureLeakageError("timestamps must be timezone-aware")
    return value.astimezone(UTC)


def _value(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _clean_bars(bars: list[Bar], cutoff: datetime) -> list[Bar]:
    cutoff = _utc(cutoff)
    if any(_utc(bar.timestamp) > cutoff for bar in bars):
        raise FeatureLeakageError("future market bar supplied to feature builder")
    deduped: dict[datetime, Bar] = {}
    for bar in bars:
        timestamp = _utc(bar.timestamp)
        current = deduped.get(timestamp)
        if current is None or bar.source.value < current.source.value:
            deduped[timestamp] = bar
    return [deduped[timestamp] for timestamp in sorted(deduped)]


def _log_return(start: float | None, end: float | None) -> float | None:
    if start is None or end is None or start <= 0 or end <= 0:
        return None
    value = math.log(end / start)
    return value if math.isfinite(value) else None


def _returns(bars: list[Bar]) -> list[float]:
    values: list[float] = []
    previous: float | None = None
    for bar in bars:
        if previous is not None:
            value = _log_return(previous, bar.close)
            if value is not None:
                values.append(value)
        previous = bar.close
    return values


def _latest_return(bars: list[Bar], periods: int) -> float | None:
    if len(bars) <= periods:
        return None
    return _log_return(bars[-periods - 1].close, bars[-1].close)


def _zscore(current: float | None, values: list[float], minimum: int = 5) -> float | None:
    if current is None or len(values) < minimum:
        return None
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / max(len(values) - 1, 1)
    if variance <= 0:
        return None
    result = (current - mean) / math.sqrt(variance)
    return result if math.isfinite(result) else None


def _beta(asset: list[float], benchmark: list[float], minimum: int = 5) -> float | None:
    pairs = list(zip(asset, benchmark, strict=False))
    if len(pairs) < minimum:
        return None
    asset_mean = sum(item[0] for item in pairs) / len(pairs)
    benchmark_mean = sum(item[1] for item in pairs) / len(pairs)
    covariance = sum((a - asset_mean) * (b - benchmark_mean) for a, b in pairs)
    variance = sum((b - benchmark_mean) ** 2 for _, b in pairs)
    if variance <= 0:
        return None
    result = covariance / variance
    return result if math.isfinite(result) else None


def _path_values(exposure: Any) -> tuple[float | None, float | None, float | None, float | None]:
    paths = list(_value(exposure, "paths", []) or [])
    weights = [_finite(_value(path, "weight")) for path in paths]
    confidences = [_finite(_value(path, "confidence")) for path in paths]
    depths = [_value(path, "depth") for path in paths]
    depth_values = [float(value) for value in depths if isinstance(value, int | float)]
    return (
        max(depth_values) if depth_values else None,
        float(len(paths)),
        max((value for value in weights if value is not None), default=None),
        max((value for value in confidences if value is not None), default=None),
    )


def build_feature_vector(
    *,
    event: Any,
    symbol: str,
    issuance_timestamp: datetime,
    data_cutoff_at: datetime,
    asset_bars: list[Bar],
    market_bars: list[Bar],
    sector_bars: list[Bar],
    exposure: Any | None = None,
    cause: Any | None = None,
    response_state: str | None = None,
) -> dict[str, float | None]:
    """Build one feature vector using only observations at or before the cutoff."""

    issuance = _utc(issuance_timestamp)
    cutoff = _utc(data_cutoff_at)
    if cutoff > issuance:
        raise FeatureLeakageError("forecast features cannot use data after issuance")
    asset = _clean_bars(asset_bars, cutoff)
    market = _clean_bars(market_bars, cutoff)
    sector = _clean_bars(sector_bars, cutoff)
    if not asset:
        raise FeatureLeakageError("asset history is required")

    asset_returns = _returns(asset)
    ret_1m = _latest_return(asset, 1)
    ret_5m = _latest_return(asset, 5)
    ret_15m = _latest_return(asset, 15)
    return_z = _zscore(ret_5m, asset_returns[:-1])
    volume_values = [float(bar.volume) for bar in asset]
    volume_z = _zscore(volume_values[-1], volume_values[:-1])
    realized = [
        math.sqrt(sum(value * value for value in asset_returns[max(0, i - 14) : i + 1]))
        for i in range(len(asset_returns))
    ]
    volatility_z = _zscore(realized[-1] if realized else None, realized[:-1])

    asset_by_time = {_utc(bar.timestamp): bar for bar in asset}
    market_by_time = {_utc(bar.timestamp): bar for bar in market}
    sector_by_time = {_utc(bar.timestamp): bar for bar in sector}
    common_market = sorted(set(asset_by_time) & set(market_by_time))
    common_sector = sorted(set(asset_by_time) & set(sector_by_time))
    aligned_asset_market = _returns([asset_by_time[timestamp] for timestamp in common_market])
    aligned_market = _returns([market_by_time[timestamp] for timestamp in common_market])
    aligned_asset_sector = _returns([asset_by_time[timestamp] for timestamp in common_sector])
    aligned_sector = _returns([sector_by_time[timestamp] for timestamp in common_sector])
    beta_market = _beta(aligned_asset_market[:-1], aligned_market[:-1])
    beta_sector = _beta(aligned_asset_sector[:-1], aligned_sector[:-1])
    market_return = _latest_return(market, 5)
    sector_return = _latest_return(sector, 5)
    market_residual = (
        None
        if beta_market is None
        else None
        if ret_5m is None or market_return is None
        else ret_5m - beta_market * market_return
    )
    sector_residual = (
        None
        if beta_sector is None
        else None
        if ret_5m is None or sector_return is None
        else ret_5m - beta_sector * sector_return
    )
    market_residual_z = _zscore(market_residual, [value for value in aligned_asset_market[:-1]])
    sector_residual_z = _zscore(sector_residual, [value for value in aligned_asset_sector[:-1]])

    path_depth, path_count, strongest_weight, strongest_confidence = _path_values(exposure)
    channels = _value(event, "economic_channels", {}) or {}
    channel_values = [_finite(value) for value in channels.values()]
    channel_values = [value for value in channel_values if value is not None]
    cause_values = {
        name: _finite(_value(cause, name))
        for name in (
            "score",
            "temporal_score",
            "entity_score",
            "economic_score",
            "graph_score",
            "market_score",
            "source_score",
        )
    }
    response = (response_state or "NOT_OBSERVED").casefold()
    response_features = {
        f"response_{name}": 1.0 if response == name else 0.0
        for name in (
            "not_observed",
            "opposite",
            "unconfirmed",
            "partial",
            "confirmed",
            "overreacting",
        )
    }
    event_timestamp = _value(event, "timestamp", issuance)
    event_age = max(0.0, (issuance - _utc(event_timestamp)).total_seconds() / 3600)
    exposure_value = _finite(_value(exposure, "exposure"))
    feature_values: dict[str, float | None] = {
        "event_severity": _finite(_value(event, "severity")),
        "event_novelty": _finite(_value(event, "novelty")),
        "event_corroboration": _finite(_value(event, "corroboration")),
        "event_confidence": _finite(_value(event, "confidence")),
        "event_independent_sources": _finite(_value(event, "independent_source_count")),
        "event_age_hours": event_age,
        "economic_channel_count": float(len(channel_values)),
        "economic_channel_signed_strength": sum(channel_values) if channel_values else None,
        "economic_channel_abs_strength": sum(abs(value) for value in channel_values)
        if channel_values
        else None,
        "graph_exposure": exposure_value,
        "graph_confidence": _finite(_value(exposure, "confidence")),
        "graph_path_depth": path_depth,
        "graph_supporting_paths": path_count,
        "graph_strongest_path_weight": strongest_weight,
        "graph_strongest_path_confidence": strongest_confidence,
        "graph_direct_company_mention": 1.0
        if symbol.upper()
        in {str(value).upper() for value in (_value(event, "companies", []) or [])}
        else 0.0,
        **{f"cause_{name}": value for name, value in cause_values.items()},
        "market_return_1m": ret_1m,
        "market_return_5m": ret_5m,
        "market_return_15m": ret_15m,
        "market_return_z": return_z,
        "market_volume_z": volume_z,
        "market_volatility_z": volatility_z,
        "market_residual": market_residual,
        "market_residual_z": market_residual_z,
        "sector_residual": sector_residual,
        "sector_residual_z": sector_residual_z,
        "absorption_residual": market_residual,
        "absorption_volume": volume_z,
        **response_features,
    }
    # Betas are retained in the forensic feature snapshot for the CAR target
    # evaluator, but are not model inputs until a deliberately versioned retrain.
    return {
        **{name: feature_values.get(name) for name in FEATURE_NAMES},
        "beta_market": beta_market,
        "beta_sector": beta_sector,
    }
