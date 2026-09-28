"""Novelty scoring: how new is this event relative to recently seen events?

Novelty is a HEURISTIC in [0, 1] (1 = nothing similar seen recently, 0 = effectively a repeat).
It is NOT a probability. Pure and deterministic: no wall clock (``now`` is passed in), no
randomness, no I/O.

Method
- Consider every ``recent`` key whose ``occurred_at`` is not in the future of ``now`` and lies
  within ``cfg.lookback_hours`` of ``candidate.occurred_at``.
- similarity_i = (w_e*entity_jaccard + w_l*location_match + w_c*class_match
                  + w_t*text_similarity) * exp(-dt_hours / time_decay_hours)
  where text_similarity = max(Jaccard, containment) over token sets, and a location match
  requires equal, known (non-empty, non-"unknown") location keys.
- novelty = clamp(1 - max_i similarity_i, 0, 1); empty or fully expired history -> 1.0.

``candidate`` / ``recent`` items are duck-typed ``fingerprint.EventKey`` values (attributes:
event_class, entity_keys, location_key, occurred_at, tokens).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from app.world.settings import NoveltyConfig

_UNKNOWN_LOCATIONS = frozenset({"", "unknown"})


def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _text_similarity(a: frozenset[str], b: frozenset[str]) -> float:
    """max(Jaccard, containment); empty on either side -> 0.0."""
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return max(inter / len(a | b), inter / min(len(a), len(b)))


def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


def _raw_similarity(candidate: Any, other: Any, cfg: NoveltyConfig) -> float:
    loc = candidate.location_key
    location = 1.0 if loc not in _UNKNOWN_LOCATIONS and loc == other.location_key else 0.0
    klass = 1.0 if candidate.event_class == other.event_class else 0.0
    return _clamp01(
        cfg.entity_weight * _jaccard(frozenset(candidate.entity_keys), frozenset(other.entity_keys))
        + cfg.location_weight * location
        + cfg.class_weight * klass
        + cfg.text_weight * _text_similarity(frozenset(candidate.tokens), frozenset(other.tokens))
    )


def _time_decay(dt_hours: float, time_decay_hours: float) -> float:
    if time_decay_hours <= 0:
        return 1.0 if dt_hours == 0 else 0.0
    return math.exp(-dt_hours / time_decay_hours)


def score_novelty(
    candidate: Any,
    recent: Sequence[Any],
    cfg: NoveltyConfig,
    now: datetime,
) -> tuple[float, dict[str, Any]]:
    """Return (novelty in [0,1], components).

    Components: ``nearest_similarity`` (decayed, 0.0 if nothing in window), ``nearest_index``
    (index into ``recent`` of the most similar key, None if none), ``history_size`` (number of
    keys in ``recent``), ``considered`` (keys inside the lookback window and not after ``now``).
    """
    now_utc = _utc(now)
    cand_at = _utc(candidate.occurred_at)

    best_sim = 0.0
    best_idx: int | None = None
    considered = 0
    for i, other in enumerate(recent):
        other_at = _utc(other.occurred_at)
        if other_at > now_utc:  # never use data from the future of `now`
            continue
        dt_hours = abs((cand_at - other_at).total_seconds()) / 3600.0
        if dt_hours > cfg.lookback_hours:
            continue
        considered += 1
        sim = _raw_similarity(candidate, other, cfg) * _time_decay(dt_hours, cfg.time_decay_hours)
        if best_idx is None or sim > best_sim:
            best_sim, best_idx = sim, i

    if best_idx is None:
        best_sim = 0.0
    novelty = _clamp01(1.0 - best_sim)
    return novelty, {
        "nearest_similarity": best_sim,
        "nearest_index": best_idx,
        "history_size": len(recent),
        "considered": considered,
    }
