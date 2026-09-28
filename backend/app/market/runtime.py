"""MarketRuntime: builds providers per settings, owns the pipeline, exposes a sync read facade.

``start()`` never raises: any failure is captured in ``error`` and the runtime stays OFFLINE, so
the API always boots. Every facade member is a plain synchronous accessor and is safe to call
in any state (OFF, unconfigured, failed, stopped).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, time
from typing import Any

from app.market.calendar import NY, MarketCalendar
from app.market.pipeline import EventSink, MarketPipeline, PipelineStatus, log_event
from app.market.providers.base import MarketDataProvider
from app.market.providers.replay import ReplayMarketDataProvider
from app.market.providers.supervisor import SupervisedProvider
from app.market.settings import MarketSettings
from app.market.types import (
    DataMode,
    ProviderHealth,
    ProviderName,
    ProviderState,
    ShockAssessment,
    SymbolFeatures,
)
from app.market.universe import Universe, get_universe
from app.schemas.event import EventCreate

logger = logging.getLogger("echo.market.runtime")

ScenarioLoader = Callable[[], Any]


def _default_scenario() -> Any:
    from app.market.fixtures import build_shock_scenario  # lazy: may not exist in some builds

    return build_shock_scenario()


class MarketRuntime:
    def __init__(
        self,
        settings: MarketSettings,
        session_factory: Callable[[], Any] | None,
        *,
        universe: Universe | None = None,
        event_sink: EventSink | None = None,
        scenario_loader: ScenarioLoader | None = None,
        pipeline_kwargs: dict[str, Any] | None = None,
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory
        self._universe = universe
        self._event_sink = event_sink
        self._scenario_loader = scenario_loader or _default_scenario
        self._pipeline_kwargs = pipeline_kwargs or {}
        self._calendar = MarketCalendar()
        self._pipeline: MarketPipeline | None = None
        self._static_healths: list[ProviderHealth] = []
        self._replay_eval_from: datetime | None = None
        self._error: str | None = None
        self._started = False

    # ------------------------------------------------------------------ lifecycle

    @property
    def pipeline(self) -> MarketPipeline | None:
        return self._pipeline

    @property
    def error(self) -> str | None:
        """Why the market feed is not running (None when healthy or intentionally off)."""
        return self._error

    async def start(self) -> None:
        """Build providers and start the pipeline. Never raises."""
        if self._started:
            return
        self._started = True
        try:
            await self._start()
        except Exception as exc:
            self._error = f"{type(exc).__name__}: {exc}"
            logger.exception("market runtime failed to start", extra={"operation": "market_start"})
            self._pipeline = None

    async def _start(self) -> None:
        choice = self._settings.echo_market_provider
        if choice == "off":
            log_event(logging.INFO, "market_runtime_off", provider="off")
            return
        universe = self._universe or get_universe()
        primary: MarketDataProvider | None
        fallback: MarketDataProvider | None = None
        if choice == "replay":
            primary = self._build_replay()
        else:
            name = ProviderName(choice)
            primary = self._build_live(name, universe)
            if self._settings.echo_market_fallback == "alpaca" and name != ProviderName.ALPACA:
                fallback = self._build_live(ProviderName.ALPACA, universe)
        if primary is None and fallback is not None:
            primary, fallback = fallback, None
        if primary is None:
            log_event(
                logging.WARNING, "market_runtime_no_provider", provider=choice, error=self._error
            )
            return
        self._pipeline = MarketPipeline(
            primary,
            universe,
            self._settings,
            self._session_factory,
            self._event_sink or self._persist_event,
            fallback=fallback,
            **{"evaluate_from": self._replay_eval_from, **self._pipeline_kwargs},
        )
        self._pipeline.start()
        log_event(logging.INFO, "market_runtime_started", provider=primary.name.value)

    def _build_replay(self) -> MarketDataProvider | None:
        try:
            scenario = self._scenario_loader()
            provider = ReplayMarketDataProvider(
                scenario.bars, speed=self._settings.echo_market_replay_speed
            )
            if scenario.bars:
                # Earlier sessions only seed baselines; only the final session is evaluated.
                last_day = max(b.timestamp for b in scenario.bars).astimezone(NY).date()
                self._replay_eval_from = datetime.combine(last_day, time(0), NY).astimezone(UTC)
            return provider
        except Exception as exc:
            self._error = f"replay scenario unavailable: {type(exc).__name__}: {exc}"
            self._static_healths.append(
                ProviderHealth(
                    provider=ProviderName.REPLAY,
                    state=ProviderState.DISCONNECTED,
                    configured=False,
                    mode=DataMode.REPLAY,
                    last_error=self._error,
                )
            )
            return None

    def _build_live(self, name: ProviderName, universe: Universe) -> MarketDataProvider | None:
        s = self._settings
        configured = s.massive_configured if name == ProviderName.MASSIVE else s.alpaca_configured
        if not configured:
            self._static_healths.append(
                ProviderHealth(
                    provider=name,
                    state=ProviderState.UNCONFIGURED,
                    configured=False,
                    mode=DataMode.LIVE,
                    last_error="credentials not configured",
                )
            )
            log_event(logging.WARNING, "provider_unconfigured", provider=name.value)
            return None
        symbols = universe.symbols()

        def factory() -> MarketDataProvider:
            if name == ProviderName.MASSIVE:
                from app.market.providers.massive import MassiveMarketDataProvider

                assert s.massive_api_key is not None
                return MassiveMarketDataProvider(s.massive_api_key.get_secret_value(), symbols)
            from app.market.providers.alpaca import AlpacaMarketDataProvider

            assert s.alpaca_api_key is not None and s.alpaca_api_secret is not None
            return AlpacaMarketDataProvider(
                s.alpaca_api_key.get_secret_value(),
                s.alpaca_api_secret.get_secret_value(),
                s.alpaca_feed,
                symbols=symbols,
            )

        try:
            return SupervisedProvider(
                factory, s.reconnect, is_active=self._calendar.expected_active
            )
        except Exception as exc:  # e.g. SDK/module missing
            err = f"provider build failed: {type(exc).__name__}: {exc}"
            self._error = self._error or err
            self._static_healths.append(
                ProviderHealth(
                    provider=name,
                    state=ProviderState.DISCONNECTED,
                    configured=True,
                    mode=DataMode.LIVE,
                    last_error=err,
                )
            )
            logger.warning("%s", err, extra={"operation": "provider_build_failed"})
            return None

    async def stop(self) -> None:
        """Stop producers, drain, flush persistence. Never raises."""
        pipeline = self._pipeline
        if pipeline is not None:
            try:
                await pipeline.stop()
            except Exception:
                logger.exception("market runtime stop failed", extra={"operation": "market_stop"})
        self._started = False

    async def _persist_event(self, event: EventCreate) -> None:
        """Default sink: canonical event in its own session; duplicate id == success."""
        if self._session_factory is None:
            return
        from app.services.events import EventService

        async with self._session_factory() as session:
            _, created = await EventService(session).create_if_absent(event)
        if not created:
            logger.info(
                "market shock event already exists event_id=%s",
                event.id,
                extra={"operation": "market_event_exists", "event_id": event.id},
            )

    # ------------------------------------------------------------------ facade (sync, safe)

    def status(self) -> PipelineStatus:
        p = self._pipeline
        q = self.queue_stats()
        return PipelineStatus(
            mode=self.mode,
            providers=self.provider_healths(),
            active_provider=self.active_provider,
            queue_depth=q["depth"],
            queue_capacity=q["capacity"],
            dropped=q["dropped"],
            subscribed_symbols=self.subscribed_symbols,
            last_observation_at=self.last_observation_at,
            replay_finished=p.replay_finished if p else False,
        )

    @property
    def mode(self) -> DataMode:
        return self._pipeline.mode if self._pipeline is not None else DataMode.OFFLINE

    def provider_healths(self) -> list[ProviderHealth]:
        live = self._pipeline.provider_healths() if self._pipeline is not None else []
        have = {h.provider for h in live}
        return live + [h for h in self._static_healths if h.provider not in have]

    @property
    def active_provider(self) -> ProviderName | None:
        if self._pipeline is None:
            return None
        active = self._pipeline.active_provider
        health = self._pipeline.health_map().get(active) if active is not None else None
        if health is not None and health.state == ProviderState.UNCONFIGURED:
            return None
        return active

    @property
    def subscribed_symbols(self) -> list[str]:
        return self._pipeline.subscribed_symbols if self._pipeline is not None else []

    @property
    def last_observation_at(self) -> datetime | None:
        return self._pipeline.last_observation_at if self._pipeline is not None else None

    def queue_stats(self) -> dict[str, int]:
        if self._pipeline is None:
            return {"depth": 0, "capacity": self._settings.echo_market_queue_size, "dropped": 0}
        return self._pipeline.queue_stats()

    @property
    def replay_finished(self) -> bool:
        return self._pipeline.replay_finished if self._pipeline is not None else False

    @property
    def session(self) -> str:
        return self._calendar.session_at(datetime.now(UTC)).value.upper()

    def latest_features(self, symbol: str) -> SymbolFeatures | None:
        if self._pipeline is None:
            return None
        return self._pipeline.latest_features.get(symbol.upper())

    def latest_assessment(self, symbol: str) -> ShockAssessment | None:
        if self._pipeline is None:
            return None
        return self._pipeline.latest_assessments.get(symbol.upper())

    def latest_price(self, symbol: str) -> tuple[float, datetime] | None:
        return self._pipeline.latest_price(symbol) if self._pipeline is not None else None

    def change_pct(self, symbol: str) -> float | None:
        return self._pipeline.change_pct(symbol) if self._pipeline is not None else None

    def state_of(self, symbol: str) -> str:
        return self._pipeline.state_of(symbol) if self._pipeline is not None else "NO_DATA"
