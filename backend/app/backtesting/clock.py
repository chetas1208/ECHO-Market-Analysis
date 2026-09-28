"""Explicit replay clock and deterministic equal-timestamp ordering."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import IntEnum


class ReplayOrder(IntEnum):
    MARKET_OBSERVATION = 1
    EVENT_ARRIVAL = 2
    FORECAST = 3
    DECISION = 4
    EXECUTION = 5
    POSITION_UPDATE = 6


def utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("replay timestamps must be timezone-aware")
    return value.astimezone(UTC)


@dataclass(frozen=True, order=True)
class ReplayTimestamp:
    timestamp: datetime
    order: ReplayOrder
    key: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "timestamp", utc(self.timestamp))


class ReplayClock:
    """A small guard object: future observations cannot be read at cutoff T."""

    def __init__(self, cutoff: datetime) -> None:
        self.cutoff = utc(cutoff)

    def available(self, timestamp: datetime) -> bool:
        return utc(timestamp) <= self.cutoff

    def require_available(self, timestamp: datetime, label: str = "observation") -> None:
        if not self.available(timestamp):
            raise ValueError(
                f"future {label} at {utc(timestamp).isoformat()} exceeds replay cutoff"
            )

    @staticmethod
    def ordered(items: list[ReplayTimestamp]) -> list[ReplayTimestamp]:
        return sorted(items, key=lambda item: (utc(item.timestamp), item.order, item.key))
