"""Operational status and metrics endpoints.

These routes are read-only. They expose no secrets or raw event/news payloads.
"""

from fastapi import APIRouter, Request, Response

from app.api.deps import HealthServiceDep
from app.observability.health import build_health
from app.observability.metrics import collect_runtime_metrics

router = APIRouter(prefix="/ops", tags=["operations"])


@router.get("/status")
async def operational_status(request: Request, service: HealthServiceDep) -> dict[str, object]:
    return await build_health(request, await service.database_ok())


def metrics_response(request: Request) -> Response:
    registry = request.app.state.metrics
    collect_runtime_metrics(registry, request.app)
    return Response(content=registry.render(), media_type="text/plain; version=0.0.4")


@router.get("/metrics", include_in_schema=False)
async def api_metrics(request: Request) -> Response:
    return metrics_response(request)
