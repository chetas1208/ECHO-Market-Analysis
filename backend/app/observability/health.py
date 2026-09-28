"""Unified operational dependency health.

Health is intentionally richer than liveness: optional feeds can be unavailable while the API
remains alive, and the response names the affected dependency and reason.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import get_settings

HEALTHY = "HEALTHY"
DEGRADED = "DEGRADED"
UNAVAILABLE = "UNAVAILABLE"


def _state(value: object) -> str:
    return str(getattr(value, "value", value)).upper()


def _provider_state(state: object, *, replay_ok: bool = False) -> tuple[str, str]:
    normalized = _state(state)
    if replay_ok and normalized == "REPLAY":
        return HEALTHY, "deterministic replay provider"
    if normalized in {"CONNECTED", "HEALTHY"}:
        return HEALTHY, "connected"
    if normalized in {"CONNECTING", "RECONNECTING", "STALE", "DEGRADED"}:
        return DEGRADED, normalized.lower()
    if normalized in {"UNCONFIGURED", "DISCONNECTED", "ERROR", "OFFLINE"}:
        return UNAVAILABLE, normalized.lower()
    return DEGRADED, normalized.lower()


async def build_health(request: Any, database_ok: bool) -> dict[str, Any]:
    dependencies: dict[str, dict[str, Any]] = {
        "database": {
            "state": HEALTHY if database_ok else UNAVAILABLE,
            "status": "connected" if database_ok else "unavailable",
            "detail": "PostgreSQL ping succeeded" if database_ok else "PostgreSQL ping failed",
        },
        "graph": {
            "state": HEALTHY if database_ok else UNAVAILABLE,
            "status": "available" if database_ok else "blocked",
            "detail": "graph snapshots are database-backed"
            if database_ok
            else "database unavailable",
        },
        "forecast": _forecast_dependency(),
        "market": _market_dependency(request),
        "world": _world_dependency(request),
        "broker": _broker_dependency(request),
        "execution": _broker_dependency(request),
    }
    states = {item["state"] for item in dependencies.values()}
    overall = (
        UNAVAILABLE
        if not database_ok
        else DEGRADED
        if DEGRADED in states or UNAVAILABLE in states
        else HEALTHY
    )
    return {
        "status": overall,
        "checked_at": datetime.now(UTC),
        "dependencies": dependencies,
        "liveness": "ok",
    }


def _forecast_dependency() -> dict[str, str]:
    path: Path = get_settings().forecast_artifact_path
    if path.exists():
        return {
            "state": HEALTHY,
            "status": "available",
            "detail": "registered forecast artifact present",
        }
    return {
        "state": UNAVAILABLE,
        "status": "unavailable",
        "detail": "forecast artifact is not available",
    }


def _market_dependency(request: Any) -> dict[str, str]:
    runtime = getattr(request.app.state, "market_runtime", None)
    if runtime is None:
        return {
            "state": UNAVAILABLE,
            "status": "unavailable",
            "detail": "market runtime is not started",
        }
    try:
        statuses = runtime.provider_healths()
        if not statuses:
            return {
                "state": UNAVAILABLE,
                "status": "unavailable",
                "detail": "no market provider configured",
            }
        values = [
            _provider_state(item.state, replay_ok=runtime.mode.value == "REPLAY")
            for item in statuses
        ]
        state = HEALTHY if any(value[0] == HEALTHY for value in values) else values[0][0]
        detail = ", ".join(
            f"{item.provider.value}:{_state(item.state).lower()}" for item in statuses
        )
        return {
            "state": state,
            "status": "connected" if state == HEALTHY else "degraded",
            "detail": detail,
        }
    except Exception as exc:
        return {"state": UNAVAILABLE, "status": "error", "detail": type(exc).__name__}


def _world_dependency(request: Any) -> dict[str, str]:
    runtime = getattr(request.app.state, "world_runtime", None)
    if runtime is None:
        return {
            "state": UNAVAILABLE,
            "status": "unavailable",
            "detail": "world runtime is not started",
        }
    try:
        health = runtime.health()
        state, detail = _provider_state(health.state, replay_ok=runtime.mode.value == "REPLAY")
        return {"state": state, "status": detail, "detail": health.last_error or detail}
    except Exception as exc:
        return {"state": UNAVAILABLE, "status": "error", "detail": type(exc).__name__}


def _broker_dependency(request: Any) -> dict[str, str]:
    service = getattr(request.app.state, "execution_service", None)
    if service is None:
        return {
            "state": UNAVAILABLE,
            "status": "unavailable",
            "detail": "execution service is not started",
        }
    try:
        health = service.health(data_fresh=False)
        if service.mode.value == "DISABLED":
            return {
                "state": UNAVAILABLE,
                "status": "disabled",
                "detail": health.message or "execution disabled",
            }
        if health.kill_switch:
            return {"state": DEGRADED, "status": "paused", "detail": "kill switch active"}
        if health.healthy:
            return {
                "state": HEALTHY,
                "status": "connected",
                "detail": health.message or "provider healthy",
            }
        return {
            "state": DEGRADED,
            "status": "unavailable",
            "detail": health.message or "provider unhealthy",
        }
    except Exception as exc:
        return {"state": UNAVAILABLE, "status": "error", "detail": type(exc).__name__}
