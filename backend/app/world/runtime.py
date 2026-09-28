"""Lifecycle owner for the world provider and ingest consumer."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from typing import Any

from app.world.fixtures import WORLD_FIXTURES
from app.world.pipeline import WorldIngestPipeline
from app.world.providers.replay import ReplayWorldEventProvider
from app.world.providers.supervisor import SupervisedWorldProvider
from app.world.providers.worldmonitor import WorldMonitorProvider
from app.world.settings import WorldSettings
from app.world.text.analyzer import AnalyzerStatus, CachingAnalyzer, NullAnalyzer
from app.world.types import WorldMode, WorldProviderHealth, WorldProviderName, WorldProviderState

logger = logging.getLogger("echo.world.runtime")


class WorldRuntime:
    def __init__(self, settings: WorldSettings, session_factory: Callable[[], Any] | None) -> None:
        self._settings = settings
        self._session_factory = session_factory
        self._provider: Any = None
        self._pipeline: WorldIngestPipeline | None = None
        self._task: asyncio.Task[None] | None = None
        self._started = False
        self._error: str | None = None
        self._analyzer = self._build_analyzer()

    @property
    def mode(self) -> WorldMode:
        health = self.health()
        if health.mode == WorldMode.REPLAY or health.state == WorldProviderState.REPLAY:
            return WorldMode.REPLAY
        if health.state in (
            WorldProviderState.HEALTHY,
            WorldProviderState.CONNECTING,
            WorldProviderState.DEGRADED,
            WorldProviderState.STALE,
        ):
            return WorldMode.LIVE
        return WorldMode.OFFLINE

    @property
    def analyzer_status(self) -> str:
        return str(
            getattr(self._analyzer, "status", AnalyzerStatus.DISABLED).value
            if hasattr(getattr(self._analyzer, "status", None), "value")
            else getattr(self._analyzer, "status", "DISABLED")
        )

    def _build_analyzer(self) -> Any:
        if self._settings.echo_world_text_model != "modernfinbert":
            return NullAnalyzer()
        try:
            from app.world.text.modernfinbert import ModernFinBERTAnalyzer

            return CachingAnalyzer(ModernFinBERTAnalyzer())
        except Exception:
            logger.exception(
                "world text analyzer unavailable", extra={"operation": "world_analyzer_init"}
            )
            return NullAnalyzer()

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        try:
            choice = self._settings.echo_world_provider
            if choice == "off":
                self._provider = None
                return
            if choice == "replay":
                self._provider = ReplayWorldEventProvider(
                    [fixture.raw for fixture in WORLD_FIXTURES.values()],
                    speed=self._settings.echo_world_replay_speed,
                )
            elif choice == "world_monitor":
                if not self._settings.world_monitor_configured:
                    self._provider = WorldMonitorProvider(
                        None,
                        base_url=self._settings.world_monitor_base_url,
                        mode=(
                            "mcp"
                            if self._settings.world_monitor_mcp_enabled
                            else self._settings.world_monitor_transport
                        ),
                        mcp_url=self._settings.world_monitor_mcp_url,
                        poll_interval_s=self._settings.echo_world_poll_interval_s,
                    )
                    return
                self._provider = SupervisedWorldProvider(
                    lambda: WorldMonitorProvider(
                        self._settings.world_monitor_api_key,
                        base_url=self._settings.world_monitor_base_url,
                        mode=(
                            "mcp"
                            if self._settings.world_monitor_mcp_enabled
                            else self._settings.world_monitor_transport
                        ),
                        mcp_url=self._settings.world_monitor_mcp_url,
                        poll_interval_s=self._settings.echo_world_poll_interval_s,
                    )
                )
            else:
                return
            self._pipeline = WorldIngestPipeline(
                self._session_factory, self._settings, self._analyzer
            )
            await self._provider.connect()
            self._task = asyncio.create_task(self._consume(), name="echo-world-consumer")
        except Exception as exc:
            self._error = f"{type(exc).__name__}: {exc}"
            logger.exception("world runtime failed to start", extra={"operation": "world_start"})

    async def _consume(self) -> None:
        assert self._provider is not None and self._pipeline is not None
        try:
            async for raw in self._provider.stream():
                await self._pipeline.ingest(raw)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._error = f"{type(exc).__name__}: {exc}"
            logger.exception("world consumer stopped", extra={"operation": "world_consumer"})

    async def stop(self) -> None:
        task, provider = self._task, self._provider
        self._task = None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        if provider is not None:
            with contextlib.suppress(Exception):
                await provider.disconnect()
        self._started = False

    def health(self) -> WorldProviderHealth:
        if self._provider is not None:
            try:
                return self._provider.health()
            except Exception as exc:
                return WorldProviderHealth(
                    provider=WorldProviderName.WORLD_MONITOR,
                    configured=False,
                    state=WorldProviderState.ERROR,
                    mode=WorldMode.OFFLINE,
                    last_error=str(exc)[:300],
                )
        return WorldProviderHealth(
            provider=WorldProviderName.WORLD_MONITOR,
            configured=False,
            state=WorldProviderState.UNCONFIGURED,
            mode=WorldMode.OFFLINE,
            last_error=self._error,
        )

    def counters(self) -> dict[str, Any]:
        counters = (
            dict(self._pipeline.counters)
            if self._pipeline is not None
            else {key: 0 for key in ("received", "created", "merged", "duplicates", "rejected")}
        )
        counters["last_event_at"] = (
            self._pipeline.last_event_at if self._pipeline is not None else None
        )
        return counters
