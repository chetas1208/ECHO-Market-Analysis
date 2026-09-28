"""Heuristic shock score. NOT a calibrated probability (decisions D-023 / Day 2 Rule 7).

score = sum_k w_k * component_k(z_k) over ret, volume, volatility, sector, market.
Each component is ``min(|z| / z_cap, 1)`` (volume uses ``max(z, 0)``: only elevated volume counts).
"""

from __future__ import annotations

import math

from app.market.settings import ShockConfig
from app.market.types import (
    FeatureStatus,
    FeatureValue,
    ShockAssessment,
    ShockDirection,
    ShockLevel,
    SymbolFeatures,
)

COMPONENT_KEYS = ("ret", "volume", "volatility", "sector", "market")


def component(z: float | None, cap: float) -> float:
    """Map a z-score to [0, 1]: ``min(|z|/cap, 1)``. None/NaN -> 0; +-inf clamps to 1."""
    if z is None or cap <= 0 or math.isnan(z):
        return 0.0
    return min(abs(z) / cap, 1.0)


def _normalised_weights(cfg: ShockConfig) -> dict[str, float]:
    raw = {k: max(float(getattr(cfg.weights, k)), 0.0) for k in COMPONENT_KEYS}
    total = sum(raw.values())
    if total <= 0:
        return {k: 1.0 / len(COMPONENT_KEYS) for k in COMPONENT_KEYS}
    return {k: v / total for k, v in raw.items()}


def _direction(f: SymbolFeatures) -> ShockDirection | None:
    for fv in (f.sector_residual, f.market_residual, f.ret_5m):
        v = fv.value
        if v is None or math.isnan(v) or v == 0:
            continue
        return ShockDirection.POSITIVE if v > 0 else ShockDirection.NEGATIVE
    return None


def _level(score: float, cfg: ShockConfig) -> ShockLevel:
    if score >= cfg.severe_threshold:
        return ShockLevel.SEVERE
    if score >= cfg.shock_threshold:
        return ShockLevel.SHOCK
    if score >= cfg.watch_threshold:
        return ShockLevel.WATCH
    return ShockLevel.NONE


def _val(fv: FeatureValue) -> float | None:
    return fv.value


def assess(f: SymbolFeatures, cfg: ShockConfig) -> ShockAssessment:
    cap = cfg.z_cap
    vol_z = _val(f.volume_z)
    components = {
        "ret": component(_val(f.return_z), cap),
        "volume": component(None if vol_z is None else max(vol_z, 0.0), cap),
        "volatility": component(_val(f.volatility_z), cap),
        "sector": component(_val(f.sector_residual_z), cap),
        "market": component(_val(f.market_residual_z), cap),
    }
    weights = _normalised_weights(cfg)
    score = sum(weights[k] * components[k] for k in COMPONENT_KEYS)
    score = min(max(score, 0.0), 1.0)
    ready = f.overall_status == FeatureStatus.READY
    level = _level(score, cfg) if ready else ShockLevel.NONE
    return ShockAssessment(
        symbol=f.symbol,
        as_of=f.as_of,
        score=score,
        level=level,
        direction=_direction(f),
        components=components,
        ready=ready,
        calibrated=False,
    )
