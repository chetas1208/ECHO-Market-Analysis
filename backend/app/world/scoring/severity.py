"""Heuristic event severity in [0, 1]: economic significance IF the event is true.

Severity is NOT sentiment and NOT a probability. It never reads headline/body wording; it only
uses structured signals (event class, entity kinds, geo scope, source-reported magnitudes and
provider importance). Deterministic, pure (no clock, no randomness).

Formula
    pre      = clamp(class_base * (1 + geo_scope + infrastructure + magnitude))
    severity = clamp((1 - w) * pre + w * provider_importance)   # w = provider_importance_weight
                                                                # (no blend if importance absent)
- class_base: ``CLASS_BASE`` table below (documented, fixed).
- geo_scope: ``cfg.geo_scope_bonus`` if a chokepoint is named (``geo.chokepoint``) or the event
  involves >= 2 distinct countries (entities of kind ``country`` or ``geo.country``).
- infrastructure: ``cfg.infrastructure_bonus`` if any entity has kind ``infrastructure``.
- magnitude: ``cfg.magnitude_bonus`` * magnitude_score (0..1), the max of the available signals:
    richter / magnitude : (v - 6) / 1 clamped to [0, 1]  (>= 7 is the full bonus, <= 6 none)
    casualties          : log10(1 + n) / 3 clamped        (>= ~1000 is full)
    outage_hours        : hours / 48 clamped              (>= 48 h is full)
  For NATURAL_DISASTER (magnitude-driven) the magnitude bonus is multiplied by
  ``MAGNITUDE_DRIVEN_FACTOR``.
- provider importance: ``raw.provider_scores["importance"]``; values in [0, 1] are used as-is,
  (1, 10] are read as a 0..10 scale, larger as 0..100. Non-finite / missing values are ignored.
"""

from __future__ import annotations

import math
from typing import Any

from app.world.settings import SeverityConfig
from app.world.types import EventClass, GeoInfo, NormalizedEntity, RawWorldEvent

CLASS_BASE: dict[EventClass, float] = {
    EventClass.MILITARY_CONFLICT: 0.70,
    EventClass.ENERGY_SUPPLY_DISRUPTION: 0.65,
    EventClass.SHIPPING_DISRUPTION: 0.60,
    EventClass.TECHNOLOGY_SUPPLY_SHOCK: 0.60,
    EventClass.SANCTION: 0.50,
    EventClass.PORT_DISRUPTION: 0.50,
    EventClass.GEOPOLITICAL_ESCALATION: 0.50,
    EventClass.NATURAL_DISASTER: 0.45,  # magnitude-driven
    EventClass.INFRASTRUCTURE_OUTAGE: 0.45,
    EventClass.CYBER_INCIDENT: 0.45,
    EventClass.COMMODITY_SHOCK: 0.45,
    EventClass.REGULATORY_EVENT: 0.35,
    EventClass.MACRO_EVENT: 0.35,
    EventClass.OTHER: 0.15,
}

MAGNITUDE_DRIVEN_FACTOR = 3.0
_MAGNITUDE_DRIVEN: frozenset[EventClass] = frozenset({EventClass.NATURAL_DISASTER})

BUCKET_HIGH = 0.70
BUCKET_ELEVATED = 0.50
BUCKET_MODERATE = 0.30


def _clamp01(x: float) -> float:
    if not math.isfinite(x):
        return 0.0
    return max(0.0, min(1.0, x))


def _finite(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _magnitude_score(magnitude: dict[str, float]) -> tuple[float, str | None]:
    """Return (score 0..1, driving key). Highest available signal wins; missing -> (0, None)."""
    best, key = 0.0, None
    for name in sorted(magnitude):
        v = _finite(magnitude[name])
        if v is None:
            continue
        lname = name.lower()
        if lname in ("richter", "magnitude"):
            s = _clamp01(v - 6.0)
        elif lname == "casualties":
            s = _clamp01(math.log10(1.0 + max(v, 0.0)) / 3.0)
        elif lname == "outage_hours":
            s = _clamp01(max(v, 0.0) / 48.0)
        else:
            continue
        if s > best:
            best, key = s, lname
    return best, key


def _importance(provider_scores: dict[str, float]) -> float | None:
    v = _finite(provider_scores.get("importance"))
    if v is None:
        return None
    if v <= 1.0:
        return _clamp01(v)
    if v <= 10.0:
        return _clamp01(v / 10.0)
    return _clamp01(v / 100.0)


def score_severity(
    event_class: EventClass,
    entities: list[NormalizedEntity],
    geo: GeoInfo,
    raw: RawWorldEvent,
    cfg: SeverityConfig,
) -> tuple[float, dict[str, Any]]:
    """Return (severity in [0,1], component breakdown). Entities are duck-typed."""
    base = CLASS_BASE.get(event_class, CLASS_BASE[EventClass.OTHER])

    countries = {
        str(getattr(e, "canonical", "")).lower()
        for e in entities
        if getattr(e, "kind", None) == "country"
    }
    chokepoint = bool(getattr(geo, "chokepoint", None))
    multi_country = len(countries) >= 2
    geo_bonus = cfg.geo_scope_bonus if (chokepoint or multi_country) else 0.0

    infra_names = sorted(
        {str(e.canonical) for e in entities if getattr(e, "kind", None) == "infrastructure"}
    )
    infra_bonus = cfg.infrastructure_bonus if infra_names else 0.0

    mag_score, mag_key = _magnitude_score(raw.magnitude or {})
    mag_bonus = cfg.magnitude_bonus * mag_score
    if event_class in _MAGNITUDE_DRIVEN:
        mag_bonus *= MAGNITUDE_DRIVEN_FACTOR

    pre = _clamp01(base * (1.0 + geo_bonus + infra_bonus + mag_bonus))

    importance = _importance(raw.provider_scores or {})
    w = _clamp01(cfg.provider_importance_weight)
    score = pre if importance is None else (1.0 - w) * pre + w * importance
    score = _clamp01(score)

    components: dict[str, Any] = {
        "class_base": base,
        "geo_scope_bonus": geo_bonus,
        "geo_scope_reason": (
            "chokepoint" if chokepoint else "multi_country" if multi_country else None
        ),
        "infrastructure_bonus": infra_bonus,
        "infrastructure_entities": infra_names,
        "magnitude_score": mag_score,
        "magnitude_key": mag_key,
        "magnitude_bonus": mag_bonus,
        "pre_blend": pre,
        "provider_importance": importance,
        "provider_importance_weight": w if importance is not None else 0.0,
        "severity": score,
    }
    return score, components


def severity_bucket(score: float) -> str:
    """HIGH >= 0.70, ELEVATED >= 0.50, MODERATE >= 0.30, else LOW."""
    if score >= BUCKET_HIGH:
        return "HIGH"
    if score >= BUCKET_ELEVATED:
        return "ELEVATED"
    if score >= BUCKET_MODERATE:
        return "MODERATE"
    return "LOW"
