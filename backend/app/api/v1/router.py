from fastapi import APIRouter

from app.api.v1 import (
    backtests,
    cause,
    events,
    execution,
    forecast,
    graph,
    health,
    ledger,
    market,
    ops,
    system,
    world,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(events.router)
api_router.include_router(market.router)
api_router.include_router(world.router)
api_router.include_router(graph.router)
api_router.include_router(cause.router)
api_router.include_router(forecast.router)
api_router.include_router(ledger.router)
api_router.include_router(backtests.router)
api_router.include_router(execution.router)
api_router.include_router(ops.router)
api_router.include_router(system.router)
