"""Provider failover selection and cross-provider bar de-duplication.

``FailoverSelector`` picks the single authoritative provider from health snapshots (with
hysteresis so a flapping primary does not cause flapping). ``BarDeduper`` guarantees each
(symbol, timestamp, interval) reaches the pipeline once, only from the authoritative provider,
so features are never computed twice for the same bar.
"""

from __future__ import annotations

from collections import OrderedDict
from datetime import datetime

from app.market.types import Bar, ProviderHealth, ProviderName, ProviderState

HEALTHY_STATES = frozenset({ProviderState.CONNECTED})


def is_healthy(health: ProviderHealth | None) -> bool:
    """CONNECTED only. DEGRADED/STALE/RECONNECTING/UNCONFIGURED/DISCONNECTED are unhealthy."""
    return health is not None and health.state in HEALTHY_STATES


class FailoverSelector:
    def __init__(
        self,
        primary: ProviderName,
        fallback: ProviderName | None = None,
        *,
        recover_after_healthy_updates: int = 3,
    ) -> None:
        if fallback is not None and fallback == primary:
            raise ValueError("fallback must differ from primary")
        if recover_after_healthy_updates < 1:
            raise ValueError("recover_after_healthy_updates must be >= 1")
        self.primary = primary
        self.fallback = fallback
        self.recover_after = recover_after_healthy_updates
        self.active: ProviderName = primary
        self.switches: int = 0
        self.reason: str = "initial: primary"
        self._primary_streak = 0

    def _switch(self, to: ProviderName, reason: str) -> None:
        if to != self.active:
            self.switches += 1
            self.active = to
        self.reason = reason
        self._primary_streak = 0

    def update(self, health_by_provider: dict[ProviderName, ProviderHealth]) -> ProviderName:
        primary_ok = is_healthy(health_by_provider.get(self.primary))
        fallback_ok = self.fallback is not None and is_healthy(
            health_by_provider.get(self.fallback)
        )
        # Streak of consecutive healthy primary observations (used only for recovery).
        self._primary_streak = self._primary_streak + 1 if primary_ok else 0

        if self.active == self.primary:
            if primary_ok:
                self.reason = "primary healthy"
            elif fallback_ok and self.fallback is not None:
                self._switch(self.fallback, "primary unhealthy; fallback healthy")
            else:
                self.reason = (
                    "primary unhealthy; no healthy fallback"
                    if self.fallback is not None
                    else "primary unhealthy; no fallback configured"
                )
            return self.active

        # Active is the fallback.
        if primary_ok and self._primary_streak >= self.recover_after:
            self._switch(self.primary, f"primary healthy for {self.recover_after} updates")
        elif fallback_ok:
            self.reason = (
                f"on fallback; primary healthy {self._primary_streak}/{self.recover_after}"
                if primary_ok
                else "on fallback; primary unhealthy"
            )
        elif primary_ok:
            self._switch(self.primary, "fallback unhealthy; primary healthy")
        else:
            self._switch(self.primary, "neither provider healthy; staying on primary")
        return self.active


class BarDeduper:
    """LRU-bounded dedupe by (symbol, timestamp, interval) across providers."""

    def __init__(self, max_keys: int = 50_000) -> None:
        if max_keys < 1:
            raise ValueError("max_keys must be >= 1")
        self.max_keys = max_keys
        self._seen: OrderedDict[tuple[str, datetime, str], ProviderName] = OrderedDict()
        self.dropped_non_active = 0
        self.dropped_duplicate = 0

    def __len__(self) -> int:
        return len(self._seen)

    def accept(self, bar: Bar, active: ProviderName) -> bool:
        """True if the bar should be processed. Bars from non-active providers are always
        dropped (authoritative provider wins); duplicates of an already-accepted key too."""
        if bar.source != active:
            self.dropped_non_active += 1
            return False
        key = (bar.symbol, bar.timestamp, bar.interval.value)
        if key in self._seen:
            self._seen.move_to_end(key)
            self.dropped_duplicate += 1
            return False
        self._seen[key] = bar.source
        if len(self._seen) > self.max_keys:
            self._seen.popitem(last=False)
        return True

    def reset(self) -> None:
        self._seen.clear()
