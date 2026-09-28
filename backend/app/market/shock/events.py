"""Turn a market shock assessment into a canonical ECHO event (``EventCreate``).

The shock score is a heuristic, NOT a calibrated probability. ``confidence`` here is the
fraction of score components that are individually strong (signal agreement) and is labelled
as such in the event metadata. Replay-sourced events are flagged ``is_mock`` so they can
never masquerade as live market data.
"""

from __future__ import annotations

import math
import re
from datetime import UTC

from app.market.types import (
    ProviderName,
    ShockAssessment,
    ShockDirection,
    SymbolFeatures,
)
from app.schemas.event import EventCreate, SourceType

EVENT_TYPE = "market_shock"
COMPONENT_AGREEMENT_THRESHOLD = 0.5
CONFIDENCE_SEMANTICS = "signal_agreement_not_probability"
_ID_SAFE = re.compile(r"[^a-z0-9]+")
_MAX_SYMBOL_ID_LEN = 24


def _num(value: float | None) -> float | None:
    """JSON-safe float: None for None/NaN/inf."""
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _fmt(value: float | None, digits: int = 2) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def _agreement(components: dict[str, float]) -> float:
    """Fraction of components >= threshold (signal agreement, not a probability)."""
    values = [_num(v) for v in components.values()]
    if not values:
        return 0.0
    strong = sum(1 for v in values if v is not None and v >= COMPONENT_AGREEMENT_THRESHOLD)
    return strong / len(values)


def build_shock_event(
    assessment: ShockAssessment,
    features: SymbolFeatures,
    provider: ProviderName,
) -> EventCreate:
    """Build the canonical event for a ready, directional shock assessment."""
    if assessment.direction is None:
        raise ValueError("cannot build shock event: assessment has no direction")
    if not assessment.ready:
        raise ValueError("cannot build shock event: assessment is not ready")
    if assessment.as_of.tzinfo is None or assessment.as_of.utcoffset() is None:
        raise ValueError("cannot build shock event: as_of must be timezone-aware")
    score = _num(assessment.score)
    if score is None:
        raise ValueError("cannot build shock event: score is not finite")

    symbol = assessment.symbol.strip().upper()
    if features.symbol.strip().upper() != symbol:
        raise ValueError(
            f"symbol mismatch between assessment ({symbol}) and features ({features.symbol})"
        )

    as_of = assessment.as_of.astimezone(UTC)
    direction = assessment.direction
    negative = direction == ShockDirection.NEGATIVE
    provider = ProviderName(provider)

    sym_id = _ID_SAFE.sub("_", symbol.lower()).strip("_")[:_MAX_SYMBOL_ID_LEN] or "unknown"
    event_id = f"evt_mkt_{sym_id}_{as_of:%Y%m%d%H%M}_{direction.value[:3]}"

    components = {k: _num(v) for k, v in assessment.components.items()}
    ret_5m = _num(features.ret_5m.value)
    return_z = _num(features.return_z.value)
    volume_z = _num(features.volume_z.value)
    volatility_z = _num(features.volatility_z.value)
    sector_residual = _num(features.sector_residual.value)
    market_residual = _num(features.market_residual.value)

    metadata = {
        "direction": direction.value,
        "level": assessment.level.value,
        "shock_score": score,
        "calibrated": False,
        "confidence_semantics": CONFIDENCE_SEMANTICS,
        "return_5m": ret_5m,
        "return_z": return_z,
        "volume_z": volume_z,
        "volume_z_method": features.volume_z_method,
        "volatility_z": volatility_z,
        "sector_residual": sector_residual,
        "market_residual": market_residual,
        "sector_benchmark": features.sector_benchmark,
        "provider": provider.value,
        "components": components,
    }

    move = "downside" if negative else "upside"
    summary = (
        f"{symbol} {assessment.level.value} {move} move at {as_of:%Y-%m-%d %H:%M} UTC. "
        f"Shock score {score:.2f} (heuristic, uncalibrated). "
        f"5m log return {_fmt(ret_5m, 4)}, return z {_fmt(return_z)} sigma, "
        f"volume z {_fmt(volume_z)} sigma, volatility z {_fmt(volatility_z)} sigma, "
        f"sector residual z {_fmt(_num(features.sector_residual_z.value))} sigma, "
        f"market residual z {_fmt(_num(features.market_residual_z.value))} sigma."
    )
    if provider == ProviderName.REPLAY:
        summary += " Source: REPLAY (not live data)."

    return EventCreate(
        id=event_id,
        timestamp=as_of,
        source_type=SourceType.MARKET,
        event_type=EVENT_TYPE,
        title=f"{symbol} abnormal {move} move",
        summary=summary,
        companies=[symbol],
        economic_channels={},
        severity=min(max(score, 0.0), 1.0),
        novelty=1.0,
        confidence=_agreement(assessment.components),
        source_refs=[{"name": provider.value}],
        metadata=metadata,
        is_mock=provider == ProviderName.REPLAY,
    )
