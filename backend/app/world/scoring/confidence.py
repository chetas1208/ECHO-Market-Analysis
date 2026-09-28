"""Interpretation-confidence scoring for world events.

Interpretation confidence -- a heuristic score, NOT a calibrated probability. It says how much
the extraction/interpretation of an event can be trusted (was it classified clearly, located,
tied to known entities, corroborated, from reliable sources, with text to interpret). It says
nothing about whether the event will move markets.

Formula (deterministic, pure; no clock, no randomness)::

    raw = 0.30 * classification_certainty
        + 0.20 * (1 if geo_resolved else 0)
        + 0.15 * min(entity_count, 4) / 4
        + 0.25 * corroboration
        + 0.10 * (source_reliability_mean if given else 0.5)
    completeness = 1.0 if has_text else 0.9
    score = clamp(raw * completeness, 0.0, 0.95)

Weights sum to 1.0, so a perfect input scores 1.0 before the 0.95 cap: no event is ever
reported as certain. Unavailable inputs (``None``) never raise and never raise the score:
they fall back to neutral-low defaults (classification certainty 0.2 = the ``OTHER`` floor,
geo unresolved, zero entities, zero corroboration, reliability 0.5). Out-of-range or
non-finite numbers are clamped/defaulted rather than rejected. Every input contributes
monotonically non-decreasing to the score.
"""

from __future__ import annotations

import math
from typing import Any

W_CLASSIFICATION = 0.30
W_GEO = 0.20
W_ENTITIES = 0.15
W_CORROBORATION = 0.25
W_RELIABILITY = 0.10

ENTITY_SATURATION = 4  # entity_count at which the entity component saturates
DEFAULT_CLASSIFICATION = 0.2  # neutral-low: matches the taxonomy OTHER fallback certainty
DEFAULT_CORROBORATION = 0.0
DEFAULT_RELIABILITY = 0.5  # neutral when no provider reliability is available
NO_TEXT_FACTOR = 0.9  # completeness penalty when there is no headline/body text to interpret
MAX_CONFIDENCE = 0.95


def _unit(value: float | None, default: float) -> float:
    """Clamp to [0, 1]; None or non-finite -> ``default``."""
    if value is None:
        return default
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(v):
        return default
    return min(1.0, max(0.0, v))


def score_confidence(
    *,
    classification_certainty: float | None,
    geo_resolved: bool | None,
    entity_count: int | None,
    corroboration: float | None,
    source_reliability_mean: float | None,
    has_text: bool,
) -> tuple[float, dict[str, Any]]:
    """Interpretation confidence -- a heuristic score, NOT a calibrated probability.

    Returns ``(score, components)`` with ``score`` in [0, 0.95]. See the module docstring for
    the weighted blend. ``components`` lists each weighted contribution, the completeness
    factor and which inputs fell back to defaults, so the score is fully auditable.
    """
    missing: list[str] = []

    if classification_certainty is None:
        missing.append("classification_certainty")
    cc = _unit(classification_certainty, DEFAULT_CLASSIFICATION)

    if geo_resolved is None:
        missing.append("geo_resolved")
    geo = 1.0 if geo_resolved else 0.0

    if entity_count is None:
        missing.append("entity_count")
    try:
        n_entities = max(0, int(entity_count)) if entity_count is not None else 0
    except (TypeError, ValueError, OverflowError):
        n_entities = 0
    ent = min(n_entities, ENTITY_SATURATION) / ENTITY_SATURATION

    if corroboration is None:
        missing.append("corroboration")
    corr = _unit(corroboration, DEFAULT_CORROBORATION)

    if source_reliability_mean is None:
        missing.append("source_reliability_mean")
    rel = _unit(source_reliability_mean, DEFAULT_RELIABILITY)

    contributions = {
        "classification_certainty": W_CLASSIFICATION * cc,
        "geo_resolved": W_GEO * geo,
        "entity_count": W_ENTITIES * ent,
        "corroboration": W_CORROBORATION * corr,
        "source_reliability": W_RELIABILITY * rel,
    }
    raw = sum(contributions.values())
    completeness = 1.0 if has_text else NO_TEXT_FACTOR
    score = round(min(MAX_CONFIDENCE, max(0.0, raw * completeness)), 6)

    components: dict[str, Any] = {
        "weights": {
            "classification_certainty": W_CLASSIFICATION,
            "geo_resolved": W_GEO,
            "entity_count": W_ENTITIES,
            "corroboration": W_CORROBORATION,
            "source_reliability": W_RELIABILITY,
        },
        "contributions": {k: round(v, 6) for k, v in contributions.items()},
        "raw": round(raw, 6),
        "completeness_factor": completeness,
        "has_text": bool(has_text),
        "capped": raw * completeness > MAX_CONFIDENCE,
        "defaulted_inputs": missing,
        "note": "interpretation confidence: heuristic score, not a calibrated probability",
    }
    return score, components
