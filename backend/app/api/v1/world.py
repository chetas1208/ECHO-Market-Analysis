"""World feed API: status of the world-event runtime (never reports replay as LIVE)."""

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request

from app.schemas.world import TextAnalyzerStatus, WorldStatus
from app.world.types import (
    WorldMode,
    WorldProviderHealth,
    WorldProviderName,
    WorldProviderState,
)

router = APIRouter(prefix="/world", tags=["world"])

_ANALYZER_STATES = ("AVAILABLE", "LOADING", "UNAVAILABLE", "DISABLED")
_ZERO_COUNTERS = ("received", "created", "merged", "duplicates", "rejected")


def _offline_health() -> WorldProviderHealth:
    return WorldProviderHealth(
        provider=WorldProviderName.WORLD_MONITOR,
        configured=False,
        state=WorldProviderState.UNCONFIGURED,
        mode=WorldMode.OFFLINE,
    )


def get_world_runtime(request: Request) -> Any:
    """The world runtime wired by the app, or None when the world feed is not running."""
    return getattr(request.app.state, "world_runtime", None)


WorldRuntimeDep = Annotated[Any, Depends(get_world_runtime)]


def _text(value: Any) -> str:
    return str(getattr(value, "value", value))


def _analyzer_status(runtime: Any) -> TextAnalyzerStatus:
    status = _text(getattr(runtime, "analyzer_status", "UNAVAILABLE")).upper()
    return status if status in _ANALYZER_STATES else "UNAVAILABLE"  # type: ignore[return-value]


def _counters(runtime: Any) -> dict[str, Any]:
    """Scalar counters only (ints plus e.g. ``last_event_at``); nested values are dropped."""
    raw = runtime.counters() or {}
    return {
        str(k): v
        for k, v in raw.items()
        if v is None or isinstance(v, int | float | str | datetime)
    }


@router.get("/status", response_model=WorldStatus)
async def world_status(runtime: WorldRuntimeDep) -> WorldStatus:
    if runtime is None:
        return WorldStatus(
            mode=WorldMode.OFFLINE,
            provider=_offline_health(),
            counters={**dict.fromkeys(_ZERO_COUNTERS, 0), "last_event_at": None},
            text_analyzer="DISABLED",
        )
    health = WorldProviderHealth.model_validate(runtime.health())
    mode = WorldMode(_text(runtime.mode))
    # Replay data must never masquerade as LIVE, whatever the runtime claims.
    replaying = (
        health.provider == WorldProviderName.REPLAY or health.state == WorldProviderState.REPLAY
    )
    if mode == WorldMode.LIVE and replaying:
        mode = WorldMode.REPLAY
    if health.mode == WorldMode.LIVE and replaying:
        health = health.model_copy(update={"mode": WorldMode.REPLAY})
    return WorldStatus(
        mode=mode,
        provider=health,
        counters=_counters(runtime),
        text_analyzer=_analyzer_status(runtime),
    )
