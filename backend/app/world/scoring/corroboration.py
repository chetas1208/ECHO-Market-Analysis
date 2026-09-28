"""Corroboration score: how well independent sources support that an event happened.

HEURISTIC in [0, 1]; deterministic; NOT a probability and NOT severity (this function takes no
severity input, and a severe event with one source stays weakly corroborated).

    effective = independent_count + syndicated_weight * syndicated_count
    base      = 1 - exp(-k * effective)
    diversity = distinct_independent_groups / total_refs        (1.0 when there are no refs)
    score     = ((1 - w) * base + w * base * diversity) * (0.9 + 0.1 * mean_reliability)

with w = ``diversity_weight``. Syndicated copies (same publisher family, wire re-publication)
add only ``syndicated_weight`` of a source to ``effective`` and also dilute diversity, so a
syndicated copy always adds strictly less than an independent source. Only groups of
independent items count towards ``distinct_groups`` (a syndicated copy never adds diversity).
The reliability factor is applied only when at least one ref carries provider reliability;
adding a low-reliability independent source can therefore lower the score slightly (the
monotone guarantee holds when reliability is absent or unchanged). Zero refs -> 0.0.

``independence`` items are duck-typed: ``.independent: bool``, ``.group: str``,
``.syndicated_of: str | None`` (see ``world.sources.SourceIndependence``).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

from app.world.settings import CorroborationConfig
from app.world.types import SourceRef


def corroboration_label(independent_count: int) -> str:
    """UI label such as '4 independent sources' (never a percentage)."""
    n = max(0, int(independent_count))
    return f"{n} independent source{'' if n == 1 else 's'}"


def score_corroboration(
    refs: Sequence[SourceRef],
    independence: Sequence[Any],
    cfg: CorroborationConfig,
) -> tuple[float, dict[str, Any]]:
    total = len(refs)
    if total == 0:
        return 0.0, {
            "independent_count": 0,
            "syndicated_count": 0,
            "distinct_groups": 0,
            "base": 0.0,
            "diversity": 1.0,
            "reliability_mean": None,
        }

    independent_count = 0
    syndicated_count = 0
    groups: set[str] = set()
    for item in independence:
        if item.independent:
            independent_count += 1
            groups.add(item.group)
        else:
            syndicated_count += 1

    effective = independent_count + cfg.syndicated_weight * syndicated_count
    base = 1.0 - math.exp(-cfg.k * effective)
    diversity = min(1.0, len(groups) / total)

    w = cfg.diversity_weight
    score = (1.0 - w) * base + w * base * diversity

    rels = [r.reliability for r in refs if r.reliability is not None]
    reliability_mean = sum(rels) / len(rels) if rels else None
    if reliability_mean is not None:
        score *= 0.9 + 0.1 * reliability_mean

    score = min(1.0, max(0.0, score))
    return score, {
        "independent_count": independent_count,
        "syndicated_count": syndicated_count,
        "distinct_groups": len(groups),
        "base": base,
        "diversity": diversity,
        "reliability_mean": reliability_mean,
    }
