"""Market API tests: a duck-typed fake runtime on app.state; DB only for bars and shocks.

Status / symbols / features run without a database. Bars and shocks need a unique
TEST_DATABASE_URL (name ending ``_test``) and are skipped otherwise.
"""

import os
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.config import Settings
from app.db.session import close_db, init_db
from app.main import create_app
from app.market.types import (
    Bar,
    DataMode,
    FeatureStatus,
    FeatureValue,
    Interval,
    ProviderHealth,
    ProviderName,
    ProviderState,
    ShockAssessment,
    ShockDirection,
    ShockLevel,
    SymbolFeatures,
)
from app.market.universe import get_universe
from app.repositories.market import MarketBarRepository
from tests.conftest import event_payload, unique_event_id

needs_db = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="set a unique TEST_DATABASE_URL (…_test) to run DB-backed market API tests",
)

T0 = datetime(2026, 9, 21, 14, 30, tzinfo=UTC)


class FakeRuntime:
    """Duck-typed MarketRuntime facade."""

    def __init__(
        self,
        mode: DataMode = DataMode.LIVE,
        *,
        active_provider: ProviderName | None = ProviderName.MASSIVE,
        providers: list[ProviderHealth] | None = None,
    ) -> None:
        self.mode = mode
        self.active_provider = active_provider
        self._providers = providers or []
        self.subscribed_symbols = ["NVDA", "SPY"]
        self.last_observation_at: datetime | None = T0
        self.replay_finished = False
        self.session = "REGULAR"
        self.features: dict[str, SymbolFeatures] = {}
        self.assessments: dict[str, ShockAssessment] = {}
        self.prices: dict[str, tuple[float, datetime]] = {}
        self.changes: dict[str, float] = {}
        self.states: dict[str, str] = {}

    def provider_healths(self) -> list[ProviderHealth]:
        return list(self._providers)

    def queue_stats(self) -> dict[str, int]:
        return {"depth": 3, "capacity": 1000, "dropped": 7}

    def latest_features(self, symbol: str) -> SymbolFeatures | None:
        return self.features.get(symbol)

    def latest_assessment(self, symbol: str) -> ShockAssessment | None:
        return self.assessments.get(symbol)

    def latest_price(self, symbol: str) -> tuple[float, datetime] | None:
        return self.prices.get(symbol)

    def change_pct(self, symbol: str) -> float | None:
        return self.changes.get(symbol)

    def state_of(self, symbol: str) -> str:
        return self.states.get(symbol, "NO_DATA")


def health(provider: ProviderName, mode: DataMode, state: ProviderState) -> ProviderHealth:
    return ProviderHealth(
        provider=provider,
        state=state,
        configured=True,
        mode=mode,
        last_message_at=T0,
        subscribed_symbols=["NVDA"],
    )


def fv(value: float | None) -> FeatureValue:
    return FeatureValue(
        value=value, status=FeatureStatus.READY if value is not None else FeatureStatus.UNAVAILABLE
    )


def nvda_features() -> SymbolFeatures:
    return SymbolFeatures(
        symbol="NVDA",
        as_of=T0,
        price=101.25,
        ret_5m=fv(-0.045),
        return_z=fv(-6.2),
        volume_z=fv(7.5),
        volatility_z=fv(3.1),
        market_residual=fv(-0.044),
        market_residual_z=fv(-5.0),
        sector_residual=fv(-0.043),
        sector_residual_z=fv(-4.9),
        volume_z_method="tod",
        sector_benchmark="SOXX",
        market_benchmark="SPY",
        overall_status=FeatureStatus.READY,
    )


def nvda_assessment() -> ShockAssessment:
    return ShockAssessment(
        symbol="NVDA",
        as_of=T0,
        score=0.86,
        level=ShockLevel.SEVERE,
        direction=ShockDirection.NEGATIVE,
        components={"ret": 0.3, "volume": 0.2},
        ready=True,
    )


def make_app(settings: Settings, runtime: Any | None) -> Any:
    app = create_app(settings, manage_db=False)
    if runtime is not None:
        app.state.market_runtime = runtime
    return app


@pytest.fixture
def no_db_settings() -> Settings:
    return Settings(_env_file=None, log_level="WARNING")


@pytest_asyncio.fixture
async def make_client(no_db_settings: Settings) -> AsyncIterator[Callable[..., httpx.AsyncClient]]:
    """Factory: DB-less client with an optional fake runtime."""
    clients: list[httpx.AsyncClient] = []

    def factory(runtime: Any | None = None) -> httpx.AsyncClient:
        app = make_app(no_db_settings, runtime)
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        http = httpx.AsyncClient(transport=transport, base_url="http://test")
        clients.append(http)
        return http

    yield factory
    for http in clients:
        await http.aclose()


# --------------------------------------------------------------------------- status


async def test_status_offline_when_no_runtime(
    make_client: Callable[..., httpx.AsyncClient],
) -> None:
    resp = await make_client(None).get("/api/v1/market/status")
    assert resp.status_code == 200
    assert resp.json() == {
        "mode": "OFFLINE",
        "providers": [],
        "active_provider": None,
        "subscribed_symbols": [],
        "last_observation_at": None,
        "queue": {"depth": 0, "capacity": 0, "dropped": 0},
        "replay_finished": False,
        "session": "CLOSED",
    }


async def test_status_live_shape(make_client: Callable[..., httpx.AsyncClient]) -> None:
    runtime = FakeRuntime(
        DataMode.LIVE,
        providers=[health(ProviderName.MASSIVE, DataMode.LIVE, ProviderState.CONNECTED)],
    )
    body = (await make_client(runtime).get("/api/v1/market/status")).json()
    assert set(body) == {
        "mode",
        "providers",
        "active_provider",
        "subscribed_symbols",
        "last_observation_at",
        "queue",
        "replay_finished",
        "session",
    }
    assert body["mode"] == "LIVE"
    assert body["active_provider"] == "massive"
    assert body["subscribed_symbols"] == ["NVDA", "SPY"]
    assert body["last_observation_at"] == "2026-09-21T14:30:00Z"
    assert body["queue"] == {"depth": 3, "capacity": 1000, "dropped": 7}
    assert body["session"] == "REGULAR"
    assert body["replay_finished"] is False
    provider = body["providers"][0]
    assert provider["provider"] == "massive"
    assert provider["state"] == "CONNECTED"
    assert provider["mode"] == "LIVE"
    assert provider["last_message_at"] == "2026-09-21T14:30:00Z"


async def test_status_replay_mode_and_finished(
    make_client: Callable[..., httpx.AsyncClient],
) -> None:
    runtime = FakeRuntime(
        DataMode.REPLAY,
        active_provider=ProviderName.REPLAY,
        providers=[health(ProviderName.REPLAY, DataMode.REPLAY, ProviderState.CONNECTED)],
    )
    runtime.replay_finished = True
    body = (await make_client(runtime).get("/api/v1/market/status")).json()
    assert body["mode"] == "REPLAY"
    assert body["active_provider"] == "replay"
    assert body["replay_finished"] is True


async def test_status_replay_provider_is_never_reported_live(
    make_client: Callable[..., httpx.AsyncClient],
) -> None:
    runtime = FakeRuntime(DataMode.LIVE, active_provider=ProviderName.REPLAY)
    body = (await make_client(runtime).get("/api/v1/market/status")).json()
    assert body["mode"] == "REPLAY"


async def test_status_offline_runtime(make_client: Callable[..., httpx.AsyncClient]) -> None:
    runtime = FakeRuntime(DataMode.OFFLINE, active_provider=None)
    runtime.subscribed_symbols = []
    runtime.last_observation_at = None
    body = (await make_client(runtime).get("/api/v1/market/status")).json()
    assert body["mode"] == "OFFLINE"
    assert body["active_provider"] is None
    assert body["last_observation_at"] is None


# --------------------------------------------------------------------------- symbols


async def test_symbols_offline_lists_whole_universe_as_no_data(
    make_client: Callable[..., httpx.AsyncClient],
) -> None:
    resp = await make_client(None).get("/api/v1/market/symbols")
    assert resp.status_code == 200
    items = resp.json()["items"]
    universe = get_universe()
    assert [i["symbol"] for i in items] == universe.symbols()
    for item in items:
        assert item["state"] == "NO_DATA"
        for key in ("price", "change_pct", "as_of", "shock_score", "volume_z", "direction"):
            assert item[key] is None
        assert item["return_5m"] is None and item["sector_residual"] is None


async def test_symbols_join_runtime_data(make_client: Callable[..., httpx.AsyncClient]) -> None:
    runtime = FakeRuntime()
    runtime.features["NVDA"] = nvda_features()
    runtime.assessments["NVDA"] = nvda_assessment()
    runtime.prices["NVDA"] = (101.25, T0)
    runtime.changes["NVDA"] = -4.5
    runtime.states["NVDA"] = "SEVERE"
    runtime.states["AMD"] = "WARMING_UP"
    runtime.prices["AMD"] = (150.0, T0)  # price but no features yet
    runtime.states["SPY"] = "NORMAL"
    items = {
        i["symbol"]: i
        for i in (await make_client(runtime).get("/api/v1/market/symbols")).json()["items"]
    }
    universe = get_universe()
    assert set(items) == set(universe.symbols())

    nvda = items["NVDA"]
    assert nvda["group"] == "semiconductors"
    assert nvda["role"] == "equity"
    assert nvda["sector_benchmark"] == "SOXX"
    assert nvda["price"] == 101.25
    assert nvda["change_pct"] == -4.5
    assert nvda["as_of"] == "2026-09-21T14:30:00Z"
    assert nvda["state"] == "SEVERE"
    assert nvda["shock_score"] == 0.86
    assert nvda["direction"] == "negative"
    assert nvda["volume_z"] == 7.5
    assert nvda["return_5m"] == -0.045
    assert nvda["sector_residual"] == -0.043

    amd = items["AMD"]
    assert amd["state"] == "WARMING_UP"
    assert amd["price"] == 150.0
    assert amd["shock_score"] is None and amd["volume_z"] is None and amd["direction"] is None

    assert items["SPY"]["role"] == "benchmark"
    assert items["SPY"]["state"] == "NORMAL"
    assert items["MSFT"]["state"] == "NO_DATA"


# --------------------------------------------------------------------------- features


async def test_features_present_includes_assessment(
    make_client: Callable[..., httpx.AsyncClient],
) -> None:
    runtime = FakeRuntime()
    runtime.features["NVDA"] = nvda_features()
    runtime.assessments["NVDA"] = nvda_assessment()
    resp = await make_client(runtime).get("/api/v1/market/features/nvda")
    assert resp.status_code == 200
    body = resp.json()
    assert body["symbol"] == "NVDA"
    assert body["as_of"] == "2026-09-21T14:30:00Z"
    assert body["overall_status"] == "READY"
    assert body["return_z"] == {"value": -6.2, "status": "READY"}
    assert body["volume_z_method"] == "tod"
    assert body["sector_benchmark"] == "SOXX"
    assert body["assessment"]["score"] == 0.86
    assert body["assessment"]["level"] == "severe"
    assert body["assessment"]["direction"] == "negative"
    assert body["assessment"]["calibrated"] is False


async def test_features_unavailable_is_not_404(
    make_client: Callable[..., httpx.AsyncClient],
) -> None:
    resp = await make_client(FakeRuntime()).get("/api/v1/market/features/NVDA")
    assert resp.status_code == 200
    body = resp.json()
    assert body["symbol"] == "NVDA"
    assert body["overall_status"] == "UNAVAILABLE"
    assert body["as_of"] is None
    assert body["assessment"] is None
    assert body["return_z"] == {"value": None, "status": "UNAVAILABLE"}
    assert body["sector_benchmark"] == "SOXX"
    assert body["market_benchmark"] == "SPY"


async def test_features_unavailable_without_runtime(
    make_client: Callable[..., httpx.AsyncClient],
) -> None:
    resp = await make_client(None).get("/api/v1/market/features/NVDA")
    assert resp.status_code == 200
    assert resp.json()["overall_status"] == "UNAVAILABLE"


async def test_features_unknown_symbol_404(make_client: Callable[..., httpx.AsyncClient]) -> None:
    resp = await make_client(FakeRuntime()).get("/api/v1/market/features/ZZZZ")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"
    assert resp.json()["error"]["request_id"]


# --------------------------------------------------------------------------- DB-backed


@pytest_asyncio.fixture
async def db_client(
    test_settings: Settings, engine: AsyncEngine
) -> AsyncIterator[Callable[..., httpx.AsyncClient]]:
    """Factory: client wired to the test database, with an optional fake runtime."""
    apps: list[Any] = []
    clients: list[httpx.AsyncClient] = []

    async def clean() -> None:
        async with engine.begin() as conn:
            await conn.execute(text("TRUNCATE market_observations"))
            await conn.execute(text("DELETE FROM canonical_events"))

    await clean()

    def factory(runtime: Any | None = None) -> httpx.AsyncClient:
        app = make_app(test_settings, runtime)
        init_db(app, test_settings)
        apps.append(app)
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        http = httpx.AsyncClient(transport=transport, base_url="http://test")
        clients.append(http)
        return http

    yield factory
    for http in clients:
        await http.aclose()
    for app in apps:
        await close_db(app)
    await clean()


def bar(
    i: int,
    *,
    symbol: str = "NVDA",
    interval: Interval = Interval.M1,
    source: ProviderName = ProviderName.MASSIVE,
    close: float = 100.5,
) -> Bar:
    return Bar(
        symbol=symbol,
        timestamp=T0 + timedelta(minutes=i * interval.minutes),
        interval=interval,
        open=100.0,
        high=max(101.0, close),
        low=min(99.0, close),
        close=close,
        volume=1000.0 + i,
        source=source,
    )


async def seed_bars(engine: AsyncEngine, bars: list[Bar]) -> None:
    async with AsyncSession(engine) as session:
        await MarketBarRepository(session).upsert_bars(bars)
        await session.commit()


@needs_db
async def test_bars_ascending_default_limit_and_shape(
    db_client: Callable[..., httpx.AsyncClient], engine: AsyncEngine
) -> None:
    await seed_bars(engine, [bar(i) for i in range(350)])
    resp = await db_client(FakeRuntime()).get("/api/v1/market/bars/NVDA")
    assert resp.status_code == 200
    body = resp.json()
    assert body["symbol"] == "NVDA" and body["interval"] == "1m"
    items = body["items"]
    assert len(items) == 300  # default limit
    stamps = [i["timestamp"] for i in items]
    assert stamps == sorted(stamps) and len(set(stamps)) == 300
    # No `start`: the newest 300 bars are returned.
    assert stamps[-1] == (T0 + timedelta(minutes=349)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert set(items[0]) == {"timestamp", "open", "high", "low", "close", "volume", "source"}
    assert items[0]["source"] == "massive"


@needs_db
async def test_bars_limit_and_time_filters(
    db_client: Callable[..., httpx.AsyncClient], engine: AsyncEngine
) -> None:
    await seed_bars(engine, [bar(i) for i in range(60)])
    client = db_client(FakeRuntime())

    resp = await client.get("/api/v1/market/bars/NVDA", params={"limit": 5})
    stamps = [i["timestamp"] for i in resp.json()["items"]]
    assert len(stamps) == 5 and stamps == sorted(stamps)
    assert stamps[-1] == "2026-09-21T15:29:00Z"

    start = (T0 + timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
    end = (T0 + timedelta(minutes=14)).isoformat().replace("+00:00", "Z")
    resp = await client.get("/api/v1/market/bars/NVDA", params={"start": start, "end": end})
    stamps = [i["timestamp"] for i in resp.json()["items"]]
    assert stamps == [
        (T0 + timedelta(minutes=m)).strftime("%Y-%m-%dT%H:%M:%SZ") for m in range(10, 15)
    ]

    resp = await client.get("/api/v1/market/bars/NVDA", params={"start": start, "limit": 3})
    assert resp.json()["items"][0]["timestamp"] == "2026-09-21T14:40:00Z"
    assert len(resp.json()["items"]) == 3  # oldest first from `start`

    resp = await client.get("/api/v1/market/bars/NVDA", params={"end": end, "limit": 2})
    assert [i["timestamp"] for i in resp.json()["items"]] == [
        "2026-09-21T14:43:00Z",
        "2026-09-21T14:44:00Z",
    ]


@needs_db
async def test_bars_limit_cap_2000_and_over_is_422(
    db_client: Callable[..., httpx.AsyncClient], engine: AsyncEngine
) -> None:
    await seed_bars(engine, [bar(i) for i in range(30)])
    client = db_client(FakeRuntime())
    assert (await client.get("/api/v1/market/bars/NVDA", params={"limit": 2000})).status_code == 200
    for bad in (5000, 2001, 0, -1):
        resp = await client.get("/api/v1/market/bars/NVDA", params={"limit": bad})
        assert resp.status_code == 422, bad
        assert resp.json()["error"]["code"] == "validation_error"


@needs_db
async def test_bars_bad_interval_and_bad_times_are_422(
    db_client: Callable[..., httpx.AsyncClient],
) -> None:
    client = db_client(FakeRuntime())
    resp = await client.get("/api/v1/market/bars/NVDA", params={"interval": "2m"})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"
    resp = await client.get("/api/v1/market/bars/NVDA", params={"start": "2026-09-21T14:30:00"})
    assert resp.status_code == 422  # naive timestamps are rejected
    resp = await client.get(
        "/api/v1/market/bars/NVDA",
        params={"start": "2026-09-21T15:00:00Z", "end": "2026-09-21T14:00:00Z"},
    )
    assert resp.status_code == 422


@needs_db
async def test_bars_unknown_symbol_404(db_client: Callable[..., httpx.AsyncClient]) -> None:
    resp = await db_client(FakeRuntime()).get("/api/v1/market/bars/ZZZZ")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


@needs_db
async def test_bars_intervals_are_separate(
    db_client: Callable[..., httpx.AsyncClient], engine: AsyncEngine
) -> None:
    await seed_bars(
        engine,
        [bar(i) for i in range(10)] + [bar(i, interval=Interval.M5) for i in range(2)],
    )
    client = db_client(FakeRuntime())
    m1 = (await client.get("/api/v1/market/bars/nvda", params={"interval": "1m"})).json()
    m5 = (await client.get("/api/v1/market/bars/NVDA", params={"interval": "5m"})).json()
    assert m1["symbol"] == "NVDA" and len(m1["items"]) == 10
    assert m5["interval"] == "5m" and len(m5["items"]) == 2


@needs_db
async def test_bars_empty_symbol_history(db_client: Callable[..., httpx.AsyncClient]) -> None:
    resp = await db_client(FakeRuntime()).get("/api/v1/market/bars/AMD")
    assert resp.status_code == 200
    assert resp.json() == {"symbol": "AMD", "interval": "1m", "items": []}


@needs_db
async def test_bars_dedup_prefers_active_provider(
    db_client: Callable[..., httpx.AsyncClient], engine: AsyncEngine
) -> None:
    bars = [bar(i, source=ProviderName.ALPACA, close=100.1) for i in range(5)]
    bars += [bar(i, source=ProviderName.MASSIVE, close=100.9) for i in range(5)]
    bars += [bar(5, source=ProviderName.REPLAY, close=100.5)]
    await seed_bars(engine, bars)

    resp = await db_client(FakeRuntime(active_provider=ProviderName.MASSIVE)).get(
        "/api/v1/market/bars/NVDA"
    )
    items = resp.json()["items"]
    stamps = [i["timestamp"] for i in items]
    assert len(items) == 6 and len(set(stamps)) == 6 and stamps == sorted(stamps)
    assert [i["source"] for i in items] == ["massive"] * 5 + ["replay"]  # preferred, else only one
    assert items[0]["close"] == 100.9


@needs_db
async def test_bars_dedup_falls_back_to_first_alphabetical_source(
    db_client: Callable[..., httpx.AsyncClient], engine: AsyncEngine
) -> None:
    bars = [bar(i, source=ProviderName.REPLAY, close=100.2) for i in range(4)]
    bars += [bar(i, source=ProviderName.MASSIVE, close=100.4) for i in range(4)]
    bars += [bar(i, source=ProviderName.ALPACA, close=100.6) for i in range(2)]
    await seed_bars(engine, bars)

    for runtime in (FakeRuntime(active_provider=None), None):
        resp = await db_client(runtime).get("/api/v1/market/bars/NVDA")
        items = resp.json()["items"]
        assert len(items) == 4
        assert [i["source"] for i in items] == ["alpaca", "alpaca", "massive", "massive"]


@needs_db
async def test_bars_dedup_still_fills_limit(
    db_client: Callable[..., httpx.AsyncClient], engine: AsyncEngine
) -> None:
    bars = [bar(i, source=ProviderName.ALPACA) for i in range(20)]
    bars += [bar(i, source=ProviderName.MASSIVE) for i in range(20)]
    await seed_bars(engine, bars)
    resp = await db_client(FakeRuntime()).get("/api/v1/market/bars/NVDA", params={"limit": 15})
    items = resp.json()["items"]
    assert len(items) == 15
    assert items[-1]["timestamp"] == "2026-09-21T14:49:00Z"  # newest 15 unique timestamps


async def _post_event(client: httpx.AsyncClient, **overrides: object) -> dict[str, Any]:
    payload = event_payload(id=unique_event_id("mkt"), **overrides)
    resp = await client.post("/api/v1/events", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


@needs_db
async def test_shocks_only_market_shock_newest_first(
    db_client: Callable[..., httpx.AsyncClient],
) -> None:
    client = db_client(FakeRuntime())
    old = await _post_event(
        client, source_type="market", event_type="market_shock", timestamp="2026-09-21T14:00:00Z"
    )
    new = await _post_event(
        client, source_type="market", event_type="market_shock", timestamp="2026-09-21T15:00:00Z"
    )
    mid = await _post_event(
        client, source_type="market", event_type="market_shock", timestamp="2026-09-21T14:30:00Z"
    )
    await _post_event(client, source_type="world", event_type="market_shock")
    await _post_event(
        client, source_type="market", event_type="volume_note", timestamp="2026-09-21T16:00:00Z"
    )
    await _post_event(client, source_type="world", event_type="supply_disruption")

    resp = await client.get("/api/v1/market/shocks")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert [i["id"] for i in items] == [new["id"], mid["id"], old["id"]]
    for item in items:
        assert item["source_type"] == "market" and item["event_type"] == "market_shock"
    assert set(items[0]) == set(new)  # same Event JSON as /events

    limited = (await client.get("/api/v1/market/shocks", params={"limit": 2})).json()["items"]
    assert [i["id"] for i in limited] == [new["id"], mid["id"]]


@needs_db
async def test_shocks_empty_and_limit_validation(
    db_client: Callable[..., httpx.AsyncClient],
) -> None:
    client = db_client(None)
    resp = await client.get("/api/v1/market/shocks")
    assert resp.status_code == 200 and resp.json() == {"items": []}
    for bad in (0, 201, -5):
        resp = await client.get("/api/v1/market/shocks", params={"limit": bad})
        assert resp.status_code == 422, bad
        assert resp.json()["error"]["code"] == "validation_error"
    assert (await client.get("/api/v1/market/shocks", params={"limit": 200})).status_code == 200


@needs_db
async def test_status_works_without_runtime_on_db_app(
    db_client: Callable[..., httpx.AsyncClient],
) -> None:
    body = (await db_client(None).get("/api/v1/market/status")).json()
    assert body["mode"] == "OFFLINE" and body["providers"] == []
