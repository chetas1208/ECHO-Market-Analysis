"""Structured JSON logging with request-id correlation."""

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
trace_id_var: ContextVar[str | None] = ContextVar("trace_id", default=None)

# Extra record attributes that are copied into the JSON line when present.
_EXTRA_FIELDS = (
    "operation",
    "trace_id",
    "event_id",
    "forecast_id",
    "graph_snapshot_id",
    "symbol",
    "provider",
    "method",
    "path",
    "status_code",
    "duration_ms",
    "error_code",
    "count",
)


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str) -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "service": self.service,
            "logger": record.name,
            "request_id": getattr(record, "request_id", None) or request_id_var.get(),
            "trace_id": getattr(record, "trace_id", None) or trace_id_var.get(),
            "message": record.getMessage(),
        }
        for key in _EXTRA_FIELDS:
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO", service: str = "echo-api") -> None:
    """Route root and uvicorn loggers through one JSON handler on stdout.

    Uvicorn's own access log is disabled: the request middleware emits an equivalent
    line that carries the request id.
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service))

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    for name in ("uvicorn", "uvicorn.error"):
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True
        logger.setLevel(level)
    access = logging.getLogger("uvicorn.access")
    access.handlers = []
    access.propagate = False
    access.disabled = True

    # SQLAlchemy/asyncpg are noisy and can include bound parameters at DEBUG.
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
