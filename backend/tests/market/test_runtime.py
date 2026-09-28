"""MarketRuntime tests: lifecycle, safe facade, never-raising start, FastAPI wiring.

Pure by default (fake providers/writers). The DB-backed tests at the bottom need a unique
TEST_DATABASE_URL (name ending ``_test``) and are skipped otherwise.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, ClassVar

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.main import create_app
from app.market.calendar import Session
from app.market.fixtures import build_shock_scenario
from app.market.runtime import MarketRuntime
from app.market.types import (
    Bar,
    DataMode,
    FeatureStatus,
    Interval,
    ProviderName,
    ProviderState,
)
from app.schemas.event import EventCreate, SourceType
from tests.market.test_pipeline import (
    T0,
    UNIV,
    FakeProvider,
    StubDetector,
    StubEngine,
    Writer,
    mk,
    settings,
    triple,
    wait_for,
)

FACADE_KEYS = {"depth", "capacity", "dropped"}


def rt(cfg: Any, **kw: Any) -> MarketRuntime:
    return MarketRuntime(cfg, None, universe=UNIV, **kw)


def scenario(minutes: int = 12) -> SimpleNamespace:
    bars = [
        b.model_copy(update={"source": ProviderName.REPLAY})
        for m in range(minutes)
        for b in triple(m)
    ]
    return SimpleNamespace(bars=bars)


def assert_offline_facade(r: MarketRuntime, capacity: int = 5000) -> None:
    assert r.mode == DataMode.OFFLINE
    assert r.active_provider is None
    assert r.subscribed_symbols == []
    assert r.last_observation_at is None
    assert r.queue_stats() == {"depth": 0, "capacity": capacity, "dropped": 0}
    assert r.replay_finished is False
    assert r.session in {s.value for s in Session}
    assert r.latest_features("NVDA") is None
    assert r.latest_assessment("NVDA") is None
    assert r.latest_price("NVDA") is None
    assert r.change_pct("NVDA") is None
    assert r.state_of("NVDA") == "NO_DATA"
    st = r.status()
    assert st.mode == DataMode.OFFLINE and st.replay_finished is False


# --------------------------------------------------------------------------- OFF / unconfigured


async def test_off_mode_starts_no_task_and_facade_is_safe() -> None:
    r = rt(settings(echo_market_provider="off"))
    await r.start()
    assert r.pipeline is None and r.error is None
    assert r.provider_healths() == []
    assert_offline_facade(r)
    await r.stop()
    await r.stop()  # idempotent


async def test_facade_is_safe_before_start_and_after_stop() -> None:
    r = rt(settings(echo_market_provider="replay"), scenario_loader=scenario)
    assert_offline_facade(r)  # never started
    await r.start()
    await r.stop()
    assert r.mode in (DataMode.REPLAY, DataMode.OFFLINE)  # no exception either way
    r.status()


@pytest.mark.parametrize("fallback", ["none", "alpaca"])
async def test_unconfigured_live_provider_boots_offline(fallback: str) -> None:
    cfg = settings(
        echo_market_provider="massive",
        echo_market_fallback=fallback,
        massive_api_key=None,
        alpaca_api_key=None,
        alpaca_api_secret=None,
    )
    r = rt(cfg)
    await r.start()  # must not raise
    assert r.pipeline is None
    healths = {h.provider: h for h in r.provider_healths()}
    assert healths[ProviderName.MASSIVE].state == ProviderState.UNCONFIGURED
    assert healths[ProviderName.MASSIVE].configured is False
    if fallback == "alpaca":
        assert healths[ProviderName.ALPACA].state == ProviderState.UNCONFIGURED
    assert_offline_facade(r)
    await r.stop()


# --------------------------------------------------------------------------- start() never raises


async def test_start_survives_scenario_loader_failure() -> None:
    def boom() -> Any:
        raise FileNotFoundError("no scenario")

    r = rt(settings(echo_market_provider="replay"), scenario_loader=boom)
    await r.start()
    assert r.pipeline is None and "no scenario" in (r.error or "")
    (h,) = r.provider_healths()
    assert h.provider == ProviderName.REPLAY and h.state == ProviderState.DISCONNECTED
    assert "no scenario" in (h.last_error or "")
    assert r.mode == DataMode.OFFLINE  # never pretends to be LIVE/REPLAY without data
    await r.stop()


async def test_start_survives_provider_factory_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    class Boom:
        def __init__(self, *a: Any, **k: Any) -> None:
            raise RuntimeError("sdk exploded")

    monkeypatch.setattr("app.market.providers.massive.MassiveMarketDataProvider", Boom)
    r = rt(settings(echo_market_provider="massive", massive_api_key=SecretStr("k")))
    await r.start()  # must not raise
    assert r.pipeline is None and "sdk exploded" in (r.error or "")
    (h,) = r.provider_healths()
    assert h.provider == ProviderName.MASSIVE and h.configured is True
    assert h.state == ProviderState.DISCONNECTED and "sdk exploded" in (h.last_error or "")
    assert_offline_facade(r)
    await r.stop()


async def test_start_survives_bad_universe_and_pipeline_constructor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def bad_universe() -> Any:
        raise ValueError("universe.yaml is broken")

    monkeypatch.setattr("app.market.runtime.get_universe", bad_universe)
    r = MarketRuntime(settings(echo_market_provider="replay"), None, scenario_loader=scenario)
    await r.start()
    assert r.pipeline is None and "universe.yaml is broken" in (r.error or "")
    await r.stop()

    class BadPipeline:
        def __init__(self, *a: Any, **k: Any) -> None:
            raise RuntimeError("ctor failed")

    monkeypatch.setattr("app.market.runtime.MarketPipeline", BadPipeline)
    r2 = rt(settings(echo_market_provider="replay"), scenario_loader=scenario)
    await r2.start()
    assert r2.pipeline is None and "ctor failed" in (r2.error or "")
    assert_offline_facade(r2)
    await r2.stop()


async def test_stop_never_raises_even_if_pipeline_stop_fails() -> None:
    r = rt(settings(echo_market_provider="replay"), scenario_loader=scenario)
    await r.start()
    assert r.pipeline is not None

    async def bad_stop(*a: Any, **k: Any) -> None:
        raise RuntimeError("stop failed")

    real_stop = r.pipeline.stop
    r.pipeline.stop = bad_stop  # type: ignore[method-assign]
    await r.stop()
    await real_stop()  # clean up the tasks the fake stop skipped


# --------------------------------------------------------------------------- replay


async def test_replay_runtime_end_to_end_facade() -> None:
    w = Writer()
    sc = scenario(12)
    r = rt(
        settings(echo_market_provider="replay", echo_market_queue_size=321),
        scenario_loader=lambda: sc,
        pipeline_kwargs={"bar_writer": w},
    )
    await r.start()
    assert r.error is None and r.pipeline is not None
    await wait_for(lambda: r.replay_finished, limit_s=30)
    try:
        # replay warm-up rule: only the last session's bars are evaluated
        assert r._replay_eval_from == datetime(2025, 3, 3, 5, 0, tzinfo=UTC)  # 00:00 ET
        last = T0 + timedelta(minutes=11)
        assert r.mode == DataMode.REPLAY  # NEVER LIVE for replay
        assert r.active_provider == ProviderName.REPLAY
        assert sorted(r.subscribed_symbols) == sorted(UNIV.symbols())
        assert r.last_observation_at == last
        assert r.queue_stats() == {"depth": 0, "capacity": 321, "dropped": 0}
        price, ts = r.latest_price("nvda") or (None, None)
        assert isinstance(price, float) and price == 111.0 and ts == last
        assert r.change_pct("NVDA") == pytest.approx((111.0 / 100.0 - 1) * 100)
        feats = r.latest_features("NVDA")
        assert feats is not None and feats.as_of == last
        assert feats.overall_status != FeatureStatus.READY  # 12 bars: still warming up
        assessment = r.latest_assessment("NVDA")
        assert assessment is not None and assessment.ready is False
        assert r.state_of("NVDA") == "WARMING_UP"
        assert r.state_of("SPY") == "NORMAL"
        assert r.state_of("MSFT") == "NO_DATA"
        assert r.latest_features("SPY") is None  # benchmarks are not evaluated
        (h,) = r.provider_healths()
        assert h.provider == ProviderName.REPLAY and h.mode == DataMode.REPLAY
        st = r.status()
        assert st.mode == DataMode.REPLAY and st.replay_finished and st.queue_capacity == 321
        assert r.session in {s.value for s in Session}
    finally:
        await r.stop()
    assert len(w.of(Interval.M1)) == 36  # flushed on completion/stop


async def test_replay_start_is_idempotent_and_restartable() -> None:
    r = rt(settings(echo_market_provider="replay"), scenario_loader=scenario)
    await r.start()
    first = r.pipeline
    await r.start()
    assert r.pipeline is first
    await r.stop()
    await r.start()
    assert r.pipeline is not first and r.pipeline is not None
    await r.stop()


# --------------------------------------------------------------------------- live via supervisor


class FakeMassive(FakeProvider):
    """Stands in for MassiveMarketDataProvider inside the real SupervisedProvider."""

    instances: ClassVar[list[FakeMassive]] = []

    def __init__(self, api_key: str, symbols: Any, **_: Any) -> None:
        bars = [mk("SPY", i, ProviderName.MASSIVE) for i in range(4)]
        super().__init__(bars, ProviderName.MASSIVE, hang=True)
        self.api_key = api_key
        FakeMassive.instances.append(self)


async def test_live_provider_runs_under_supervisor_and_stop_flushes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.market.providers.massive.MassiveMarketDataProvider", FakeMassive)
    FakeMassive.instances.clear()
    w = Writer()
    r = rt(
        settings(echo_market_provider="massive", massive_api_key=SecretStr("secret-key")),
        pipeline_kwargs={
            "bar_writer": w,
            "feature_engine": StubEngine(),
            "detector": StubDetector(),
            "batch_size": 10_000,
            "flush_interval_s": 3600.0,
        },
    )
    await r.start()
    assert r.error is None and r.pipeline is not None
    try:
        await wait_for(
            lambda: r.latest_price("SPY") is not None and r.latest_price("SPY")[0] == 103.0
        )
        assert r.mode == DataMode.LIVE  # supervised + CONNECTED
        assert r.active_provider == ProviderName.MASSIVE
        (h,) = r.provider_healths()
        assert h.provider == ProviderName.MASSIVE and h.state == ProviderState.CONNECTED
        assert h.messages_received == 4
        assert not r.replay_finished
        assert w.writes == []  # buffered: no DB write per bar / per batch
    finally:
        await r.stop()
    assert len(w.of(Interval.M1)) == 4  # flushed on stop
    assert FakeMassive.instances[0].api_key == "secret-key"


# --------------------------------------------------------------------------- FastAPI wiring


def _app_settings() -> Settings:
    return Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://echo:echo@localhost:1/none_test",
        log_level="WARNING",
    )


async def test_lifespan_wires_runtime_on_app_state_and_status_endpoint() -> None:
    app = create_app(
        _app_settings(), manage_db=False, market_settings=settings(echo_market_provider="off")
    )
    async with app.router.lifespan_context(app):
        runtime = app.state.market_runtime
        assert isinstance(runtime, MarketRuntime) and runtime.mode == DataMode.OFFLINE
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            resp = await client.get("/api/v1/market/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["mode"] == "OFFLINE" and body["replay_finished"] is False
        assert set(body["queue"]) == FACADE_KEYS


async def test_lifespan_boots_even_if_runtime_start_and_stop_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def boom(self: MarketRuntime) -> None:
        raise RuntimeError("market exploded")

    monkeypatch.setattr(MarketRuntime, "start", boom)
    monkeypatch.setattr(MarketRuntime, "stop", boom)
    app = create_app(
        _app_settings(), manage_db=False, market_settings=settings(echo_market_provider="replay")
    )
    async with app.router.lifespan_context(app):
        assert isinstance(app.state.market_runtime, MarketRuntime)


async def test_invalid_market_settings_fall_back_to_off(monkeypatch: pytest.MonkeyPatch) -> None:
    def bad() -> Any:
        raise ValueError("invalid ECHO_MARKET_QUEUE_SIZE")

    monkeypatch.setattr("app.main.get_market_settings", bad)
    app = create_app(_app_settings(), manage_db=False)
    async with app.router.lifespan_context(app):
        assert app.state.market_runtime.mode == DataMode.OFFLINE
        assert app.state.market_runtime.pipeline is None


async def test_lifespan_replay_runtime_is_stopped_on_shutdown() -> None:
    app = create_app(
        _app_settings(),
        manage_db=False,
        market_settings=settings(echo_market_provider="replay", echo_market_replay_speed=1.0),
    )
    async with app.router.lifespan_context(app):
        await asyncio.sleep(0.05)
    runtime = app.state.market_runtime
    assert runtime.pipeline is not None and runtime.pipeline.finished  # stop() drained + flushed
    assert all(t.done() for t in runtime.pipeline._tasks)


# --------------------------------------------------------------------------- DB-backed

needs_db = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="set a unique TEST_DATABASE_URL (…_test) to run DB-backed runtime tests",
)


@pytest.fixture
async def session_factory(engine: AsyncEngine) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE market_observations"))
        await conn.execute(text("DELETE FROM canonical_events"))
    yield factory
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE market_observations"))
        await conn.execute(text("DELETE FROM canonical_events"))


def _event(event_id: str = "evt_mkt_nvda_202609161600_neg") -> EventCreate:
    return EventCreate(
        id=event_id,
        timestamp=datetime(2026, 9, 16, 16, 0, tzinfo=UTC),
        source_type=SourceType.MARKET,
        event_type="market_shock",
        title="NVDA abnormal downside move",
        companies=["NVDA"],
        severity=0.9,
        novelty=1.0,
        confidence=0.8,
        is_mock=True,
    )


@needs_db
async def test_default_sink_creates_event_and_duplicate_is_success(
    session_factory: async_sessionmaker[AsyncSession], engine: AsyncEngine
) -> None:
    r = MarketRuntime(settings(echo_market_provider="off"), session_factory)
    await r._persist_event(_event())
    await r._persist_event(_event())  # same deterministic id: harmless, no exception
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text("SELECT source_type, event_type, is_mock FROM canonical_events")
            )
        ).all()
    assert [tuple(x) for x in rows] == [("MARKET", "market_shock", True)]


@needs_db
async def test_replay_runtime_persists_bars_in_batches_and_shock_event_to_db(
    session_factory: async_sessionmaker[AsyncSession], engine: AsyncEngine
) -> None:
    sc = build_shock_scenario()
    assert sc.expected_shock_at is not None
    expected = sc.expected_shock_at
    bars: list[Bar] = [b for b in sc.bars if b.timestamp <= expected + timedelta(minutes=10)]
    opened = 0

    def counting_factory() -> AsyncSession:
        nonlocal opened
        opened += 1
        return session_factory()

    r = MarketRuntime(
        settings(echo_market_provider="replay"),
        counting_factory,
        scenario_loader=lambda: SimpleNamespace(bars=bars),
        # the real universe is used; only shortcut: skip evaluating the warm-up sessions
        pipeline_kwargs={"evaluate_from": expected - timedelta(minutes=10)},
    )
    await r.start()
    await wait_for(lambda: r.replay_finished, limit_s=120)
    await r.stop()
    assert r.mode in (DataMode.REPLAY, DataMode.OFFLINE) and r.mode != DataMode.LIVE
    async with engine.connect() as conn:
        n_bars = (await conn.execute(text("SELECT count(*) FROM market_observations"))).scalar_one()
        n_1m = (
            await conn.execute(
                text("SELECT count(*) FROM market_observations WHERE timeframe = '1m'")
            )
        ).scalar_one()
        n_5m = (
            await conn.execute(
                text("SELECT count(*) FROM market_observations WHERE timeframe='5m'")
            )
        ).scalar_one()
        sources = (
            (await conn.execute(text("SELECT DISTINCT source FROM market_observations")))
            .scalars()
            .all()
        )
        shocks = (
            await conn.execute(
                text(
                    "SELECT id, timestamp, is_mock, severity FROM canonical_events "
                    "WHERE source_type='MARKET' AND event_type='market_shock'"
                )
            )
        ).all()
    assert n_1m == len(bars) and n_5m > 0 and n_bars > n_1m
    assert set(sources) == {"replay"}
    assert opened < len(bars) // 50  # batched: far fewer sessions than bars
    assert shocks, "no market_shock event persisted"
    assert all(s.is_mock for s in shocks)
    assert abs((shocks[0].timestamp - expected).total_seconds()) <= 5 * 60
