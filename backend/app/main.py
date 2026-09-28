"""ECHO API application factory."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import register_exception_handlers
from app.api.v1.ops import metrics_response
from app.api.v1.router import api_router
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.db.session import close_db, init_db
from app.execution.service import ExecutionService
from app.execution.settings import get_execution_settings
from app.market.runtime import MarketRuntime
from app.market.settings import MarketSettings, get_market_settings
from app.observability.metrics import MetricsRegistry
from app.world.runtime import WorldRuntime
from app.world.settings import WorldSettings, get_world_settings

logger = logging.getLogger("echo.market")


def _resolve_market_settings(explicit: MarketSettings | None) -> MarketSettings:
    """Market config can never block API startup: fall back to feed OFF on invalid config."""
    if explicit is not None:
        return explicit
    try:
        return get_market_settings()
    except Exception:
        logger.exception("invalid market settings; market feed disabled")
        return MarketSettings(_env_file=None, echo_market_provider="off")


def create_app(
    settings: Settings | None = None,
    *,
    manage_db: bool = True,
    market_settings: MarketSettings | None = None,
    world_settings: WorldSettings | None = None,
) -> FastAPI:
    """Build the app. ``manage_db=False`` lets tests wire their own engine;
    ``market_settings`` overrides the env-driven market config (tests)."""
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.service_name)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if manage_db:
            init_db(app, settings)

        def session_factory() -> Any:  # resolved lazily: tests may wire the engine later
            return app.state.session_factory()

        runtime: MarketRuntime | None = None
        world_runtime: WorldRuntime | None = None
        try:
            runtime = MarketRuntime(_resolve_market_settings(market_settings), session_factory)
            app.state.market_runtime = runtime
            await runtime.start()  # never raises; a market failure must not block the API
        except Exception:
            logger.exception("market runtime startup failed; API continues without market data")
        try:
            resolved_world = world_settings or get_world_settings()
            world_runtime = WorldRuntime(resolved_world, session_factory)
            app.state.world_runtime = world_runtime
            await world_runtime.start()
        except Exception:
            logger.exception("world runtime startup failed; API continues without world data")
        try:
            yield
        finally:
            if runtime is not None:
                try:
                    await runtime.stop()
                except Exception:
                    logger.exception("market runtime shutdown failed")
            if world_runtime is not None:
                try:
                    await world_runtime.stop()
                except Exception:
                    logger.exception("world runtime shutdown failed")
            if manage_db:
                await close_db(app)

    app = FastAPI(title="ECHO API", version="0.2.0-dev", lifespan=lifespan)
    app.state.settings = settings
    app.state.metrics = MetricsRegistry()
    app.state.execution_service = ExecutionService(get_execution_settings())

    # Added last = outermost: CORS wraps request-context so preflights are answered first.
    app.add_middleware(RequestContextMiddleware, metrics=app.state.metrics)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-Request-ID", "X-Trace-ID"],
        expose_headers=["X-Request-ID", "X-Trace-ID"],
    )
    register_exception_handlers(app)
    app.include_router(api_router)
    app.add_api_route("/metrics", metrics_response, methods=["GET"], include_in_schema=False)
    return app


app = create_app()
