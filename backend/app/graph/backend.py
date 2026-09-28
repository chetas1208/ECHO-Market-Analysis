"""Safe graph backend selection and status reporting.

The application graph path remains deterministic and bounded. AURE is an
optional local persistence backend; this module never pretends it is healthy
merely because a path was configured.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from app.core.config import Settings


@dataclass(frozen=True)
class GraphBackendStatus:
    requested: str
    active: str
    fallback: str
    state: str
    reason: str


def _binary(settings: Settings) -> Path | None:
    if settings.aure_binary is not None:
        return settings.aure_binary
    discovered = shutil.which("aure")
    return Path(discovered) if discovered else None


def resolve_graph_backend(settings: Settings) -> GraphBackendStatus:
    requested = settings.graph_backend
    fallback = settings.graph_fallback_backend
    if requested == "networkx":
        return GraphBackendStatus(requested, "networkx", fallback, "READY", "configured")

    binary = _binary(settings)
    db_path = settings.aure_database_path
    if not settings.aure_enabled:
        reason = "AURE_ENABLED is false"
    elif binary is None:
        reason = "AURE binary is not configured or not on PATH"
    elif db_path is None:
        reason = "AURE_DATABASE_PATH is not configured"
    elif not binary.exists():
        reason = "configured AURE binary does not exist"
    elif not binary.is_file() or not binary.stat().st_mode & 0o111:
        reason = "configured AURE binary is not executable"
    elif not db_path.exists():
        reason = "configured AURE database does not exist"
    else:
        return GraphBackendStatus(requested, "aure", fallback, "CONFIGURED", "paths configured")

    if fallback == "networkx":
        return GraphBackendStatus(requested, "networkx", fallback, "FALLBACK", reason)
    return GraphBackendStatus(requested, "unavailable", fallback, "ERROR", reason)
