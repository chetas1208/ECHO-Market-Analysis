import asyncio
import logging
import time

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.health import HealthRepository

logger = logging.getLogger("echo.health")

DB_CHECK_TIMEOUT_SECONDS = 3.0


class HealthService:
    def __init__(self, session: AsyncSession) -> None:
        self.repo = HealthRepository(session)

    async def database_ok(self) -> bool:
        started = time.perf_counter()
        try:
            await asyncio.wait_for(self.repo.ping(), timeout=DB_CHECK_TIMEOUT_SECONDS)
        except Exception as exc:
            logger.warning(
                "database readiness check failed",
                extra={"operation": "health.ready", "error_code": type(exc).__name__},
            )
            return False
        metrics = self.repo.session.info.get("metrics")
        if metrics is not None:
            metrics.observe(
                "echo_db_ping_duration_seconds",
                time.perf_counter() - started,
                help_text="Database health-check latency in seconds.",
            )
        return True
