"""Pure-ASGI middleware: request-id propagation and access logging."""

import logging
import re
import time
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging import request_id_var, trace_id_var
from app.observability.metrics import MetricsRegistry

logger = logging.getLogger("echo.access")

REQUEST_ID_HEADER = "x-request-id"
TRACE_ID_HEADER = "x-trace-id"
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._\-]{1,128}$")


class RequestContextMiddleware:
    """Assigns or propagates X-Request-ID and logs one line per request."""

    def __init__(self, app: ASGIApp, metrics: MetricsRegistry | None = None) -> None:
        self.app = app
        self.metrics = metrics

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = None
        for name, value in scope["headers"]:
            if name == REQUEST_ID_HEADER.encode():
                incoming = value.decode("latin-1")
                break
        if incoming and _VALID_REQUEST_ID.match(incoming):
            request_id = incoming
        else:
            request_id = uuid.uuid4().hex

        incoming_trace = None
        for name, value in scope["headers"]:
            if name == TRACE_ID_HEADER.encode():
                incoming_trace = value.decode("latin-1")
                break
        trace_id = (
            incoming_trace
            if incoming_trace and _VALID_REQUEST_ID.match(incoming_trace)
            else request_id
        )

        scope.setdefault("state", {})["request_id"] = request_id
        scope["state"]["trace_id"] = trace_id
        request_token = request_id_var.set(request_id)
        trace_token = trace_id_var.set(trace_id)
        started = time.perf_counter()
        status_code = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = [
                    (k, v)
                    for k, v in message.get("headers", [])
                    if k.lower() not in {b"x-request-id", b"x-trace-id"}
                ]
                headers.append((b"x-request-id", request_id.encode("latin-1")))
                headers.append((b"x-trace-id", trace_id.encode("latin-1")))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            logger.info(
                "request completed",
                extra={
                    "operation": "http.request",
                    "method": scope["method"],
                    "path": scope["path"],
                    "status_code": status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                },
            )
            if self.metrics is not None:
                elapsed_s = time.perf_counter() - started
                self.metrics.inc(
                    "echo_http_requests_total",
                    labels={
                        "method": scope["method"],
                        "path": scope["path"],
                        "status": status_code,
                    },
                    help_text="HTTP requests completed.",
                )
                self.metrics.observe(
                    "echo_http_request_duration_seconds",
                    elapsed_s,
                    labels={"method": scope["method"], "path": scope["path"]},
                    help_text="HTTP request duration in seconds.",
                )
                if status_code >= 500:
                    self.metrics.inc(
                        "echo_http_errors_total",
                        labels={"method": scope["method"], "path": scope["path"]},
                        help_text="HTTP 5xx responses.",
                    )
            trace_id_var.reset(trace_token)
            request_id_var.reset(request_token)
