"""Per-(symbol, direction) shock alert cooldown. Deterministic: time comes only from `as_of`."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.market.types import ShockDirection, ShockLevel

_EMIT_RANK: dict[ShockLevel, int] = {ShockLevel.SHOCK: 1, ShockLevel.SEVERE: 2}


@dataclass
class _State:
    emitted_at: datetime
    level: ShockLevel


class ShockCooldown:
    """Suppress repeat shock events for the same (symbol, direction) within a cooldown."""

    def __init__(self, cooldown_seconds: float) -> None:
        if cooldown_seconds < 0:
            raise ValueError("cooldown_seconds must be >= 0")
        self.cooldown_seconds = cooldown_seconds
        self._state: dict[tuple[str, ShockDirection], _State] = {}

    def should_emit(
        self,
        symbol: str,
        direction: ShockDirection | None,
        level: ShockLevel,
        as_of: datetime,
    ) -> bool:
        """Return True (and record the emit) if an event should be emitted now."""
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        rank = _EMIT_RANK.get(level)
        if rank is None or direction is None:
            return False
        key = (symbol, direction)
        prev = self._state.get(key)
        if prev is None:
            self._state[key] = _State(as_of, level)
            return True
        elapsed = (as_of - prev.emitted_at).total_seconds()
        if elapsed < 0:  # out-of-order: never emit, never touch state
            return False
        if elapsed >= self.cooldown_seconds or rank > _EMIT_RANK[prev.level]:
            self._state[key] = _State(as_of, level)
            return True
        return False

    def reset(self) -> None:
        self._state.clear()

    def snapshot(self) -> dict[str, Any]:
        """JSON-serializable view of cooldown state."""
        entries = [
            {
                "symbol": sym,
                "direction": d.value,
                "level": st.level.value,
                "last_emit_at": st.emitted_at.isoformat(),
            }
            for (sym, d), st in sorted(self._state.items(), key=lambda kv: (kv[0][0], kv[0][1]))
        ]
        return {"cooldown_seconds": self.cooldown_seconds, "entries": entries}
