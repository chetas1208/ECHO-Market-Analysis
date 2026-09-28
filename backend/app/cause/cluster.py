"""Explainable structured cluster-shock detector."""

from __future__ import annotations

import hashlib
import math
from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import UTC, timedelta

from app.cause.types import CauseConfig, ClusterShockValue, ObservedShock


def detect_clusters(
    shocks: Iterable[ObservedShock],
    memberships: Mapping[str, set[str]],
    config: CauseConfig,
    *,
    source_event_id: str | None = None,
) -> list[ClusterShockValue]:
    """Find synchronized, directional moves inside declared structured groups.

    Memberships come from sectors or ShockGraph neighborhoods, never price correlation.
    """
    grouped: dict[str, list[ObservedShock]] = defaultdict(list)
    for shock in shocks:
        if shock.residual_z is None or not math.isfinite(shock.residual_z):
            continue
        if abs(shock.residual_z) < config.cluster_min_residual_z:
            continue
        for group in sorted(memberships.get(shock.symbol, set())):
            grouped[group].append(shock)

    results: list[ClusterShockValue] = []
    sync_window = timedelta(minutes=config.cluster_sync_minutes)
    for group, candidates in sorted(grouped.items()):
        by_symbol = {item.symbol: item for item in candidates}
        members = sorted(by_symbol.values(), key=lambda item: (item.timestamp, item.symbol))
        if len(members) < config.cluster_min_members:
            continue
        start = min(item.timestamp for item in members).astimezone(UTC)
        end = max(item.timestamp for item in members).astimezone(UTC)
        span = end - start
        if span > sync_window:
            continue
        positive = sum(item.direction.casefold() in {"positive", "up"} for item in members)
        negative = len(members) - positive
        direction = "POSITIVE" if positive >= negative else "NEGATIVE"
        agreement = max(positive, negative) / len(members)
        synchronization = max(0.0, 1.0 - span.total_seconds() / sync_window.total_seconds())
        volume_values = [
            1.0
            if item.volume_z is not None and item.volume_z >= config.cluster_min_volume_z
            else 0.0
            for item in members
        ]
        volume_confirmation = sum(volume_values) / len(volume_values)
        average_residual = sum(abs(float(item.residual_z or 0)) for item in members) / len(members)
        strength = min(1.0, average_residual / 4.0) * agreement * synchronization
        member_ids = [item.event_id for item in members]
        digest = hashlib.sha256(
            (group + "|" + direction + "|" + "|".join(member_ids)).encode("utf-8")
        ).hexdigest()[:20]
        results.append(
            ClusterShockValue(
                cluster_id=f"cluster_{digest}",
                cluster_key=group,
                as_of=end,
                direction=direction,
                members=[item.symbol for item in members],
                member_count=len(members),
                abnormal_count=len(members),
                strength=round(min(max(strength, 0.0), 1.0), 6),
                synchronization=round(synchronization, 6),
                volume_confirmation=round(volume_confirmation, 6),
                graph_connectivity=1.0,
                source_event_id=source_event_id,
                metadata={
                    "directional_agreement": round(agreement, 6),
                    "time_span_seconds": round(span.total_seconds(), 3),
                    "memberships": group,
                },
            )
        )
    return sorted(results, key=lambda item: (-item.strength, item.cluster_key, item.cluster_id))
