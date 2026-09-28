from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.api.deps import HealthServiceDep
from app.schemas.common import HealthResponse, ReadyResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Liveness: the process is up. Does not touch the database."""
    return HealthResponse(status="ok")


@router.get("/ready", response_model=ReadyResponse, responses={503: {"model": ReadyResponse}})
async def ready(service: HealthServiceDep) -> ReadyResponse | JSONResponse:
    """Readiness: dependencies (PostgreSQL) are reachable."""
    if await service.database_ok():
        return ReadyResponse(status="ready", checks={"database": "ok"})
    return JSONResponse(
        status_code=503,
        content={"status": "not_ready", "checks": {"database": "error"}},
    )
