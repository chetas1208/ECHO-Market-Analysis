"""Application errors and the uniform error envelope."""

from typing import Any


class AppError(Exception):
    """Base class for errors that map to an HTTP error envelope."""

    status_code = 500
    code = "internal_error"

    def __init__(self, message: str, details: Any | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class DatabaseError(AppError):
    status_code = 503
    code = "database_error"


class GraphSnapshotError(AppError):
    """Graph snapshot is absent or fails its content-integrity check."""

    status_code = 503
    code = "graph_snapshot_error"


class CauseDependencyError(AppError):
    """Cause analysis cannot run because a required historical dependency is absent."""

    status_code = 503
    code = "cause_dependency_error"


def error_body(
    code: str, message: str, request_id: str, details: Any | None = None
) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message, "request_id": request_id}
    if details is not None:
        error["details"] = details
    return {"error": error}
