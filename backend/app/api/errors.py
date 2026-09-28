"""Exception handlers: every error leaves the API in the same envelope."""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError, SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.errors import AppError, error_body
from app.db.session import DB_CONNECTIVITY_ERRORS

logger = logging.getLogger("echo.errors")

_HTTP_CODES = {404: "not_found", 405: "method_not_allowed"}


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", None) or "unknown"


def _respond(
    request: Request, status_code: int, code: str, message: str, details: Any | None = None
) -> JSONResponse:
    rid = _request_id(request)
    return JSONResponse(
        status_code=status_code,
        content=error_body(code, message, rid, details),
        headers={"X-Request-ID": rid},
    )


def _validation_details(exc: RequestValidationError) -> list[dict[str, Any]]:
    # Deliberately drops `input`/`ctx`: they may echo payload content or be unserializable.
    return [
        {"loc": list(err.get("loc", ())), "msg": err.get("msg", ""), "type": err.get("type", "")}
        for err in exc.errors()
    ]


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        if exc.status_code >= 500:
            logger.error(exc.message, extra={"operation": "http.error", "error_code": exc.code})
        return _respond(request, exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return _respond(
            request,
            422,
            "validation_error",
            "Request validation failed",
            _validation_details(exc),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        fallback = "internal_error" if exc.status_code >= 500 else "http_error"
        code = _HTTP_CODES.get(exc.status_code, fallback)
        message = str(exc.detail) if exc.detail else "HTTP error"
        response = _respond(request, exc.status_code, code, message)
        if exc.headers:  # e.g. Allow on 405
            response.headers.update(exc.headers)
        return response

    async def database_handler(request: Request, exc: Exception) -> JSONResponse:
        connectivity = not isinstance(exc, SQLAlchemyError) or isinstance(
            exc, OperationalError | InterfaceError
        )
        if isinstance(exc, DBAPIError) and exc.connection_invalidated:
            connectivity = True
        logger.error(
            "database error",
            exc_info=exc,
            extra={
                "operation": "http.error",
                "error_code": "database_error",
                "request_id": _request_id(request),
            },
        )
        return _respond(
            request,
            503 if connectivity else 500,
            "database_error",
            "The database is unavailable" if connectivity else "A database error occurred",
        )

    for exc_type in (SQLAlchemyError, *DB_CONNECTIVITY_ERRORS):
        app.add_exception_handler(exc_type, database_handler)

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "unhandled exception",
            exc_info=exc,
            extra={
                "operation": "http.error",
                "error_code": "internal_error",
                "request_id": _request_id(request),
            },
        )
        return _respond(request, 500, "internal_error", "Internal server error")
