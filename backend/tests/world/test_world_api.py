"""Day 3 API: /events filters, /events/{id}/sources, /world/status.

DB tests need a unique TEST_DATABASE_URL (name ending ``_test``). Events and evidence are
immutable/FK-protected and cannot be deleted, so the seed is written through WorldRepository
inside an outer transaction that the app's session dependency joins (commits become savepoint
releases) and that is rolled back per test; nothing persists, so other suites' table cleanup
never hits a RESTRICT foreign key. The seed is dated in 2031 and queries use that window. The
status tests use a fake runtime and never touch the database.
"""

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.config import Settings
from app.db.session import get_session
from app.main import create_app
from app.repositories.events import EventRepository
from app.repositories.world import WorldRepository
from app.world.types import (
    WorldMode,
    WorldProviderHealth,
    WorldProviderName,
    WorldProviderState,
)

needs_db = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="set a unique TEST_DATABASE_URL (…_test) to run DB-backed world API tests",
)

T0 = datetime(2031, 3, 1, 10, 0, tzinfo=UTC)
WINDOW = {"start": "2031-03-01T00:00:00Z", "end": "2031-03-02T00:00:00Z"}

# key -> (event_type, source_type, severity, hour offset)
SEED: dict[str, tuple[str, str, float, int]] = {
    "geo": ("military_conflict", "WORLD", 0.90, 0),
    "energy": ("energy_supply_disruption", "WORLD", 0.70, 1),
    "supply": ("shipping_disruption", "WORLD", 0.50, 2),
    "tech": ("cyber_incident", "WORLD", 0.30, 3),
    "macro": ("macro_event", "WORLD", 0.60, 4),
    "other": ("other", "WORLD", 0.10, 5),
    "shock": ("market_shock", "MARKET", 0.80, 6),
    "sanction": ("sanction", "WORLD", 0.95, 7),
}


def eid(key: str) -> str:
    return f"evt_d3api_{key}"


def _values(key: str) -> dict[str, Any]:
    event_type, source_type, severity, hour = SEED[key]
    return {
        "id": eid(key),
        "timestamp": T0 + timedelta(hours=hour),
        "source_type": source_type,
        "event_type": event_type,
        "title": f"Seed {key}",
        "severity": severity,
        "novelty": 0.5,
        "corroboration": 0.2,
        "confidence": 0.7,
    }


def _source(n: int, **overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "provider": "replay",
        "source_name": f"Outlet {n}",
        "source_group": "wire" if n == 1 else "press",
        "source_url": f"https://example.test/{n}",
        "source_identifier": f"prov-{n}",
        "headline": f"Headline {n}",
        "published_at": T0 + timedelta(minutes=n),
        "retrieved_at": T0 + timedelta(minutes=n, seconds=30),
        "is_independent": n != 2,
        "syndicated_from": "Outlet 1" if n == 2 else None,
        "reliability": 0.9 if n == 1 else None,
        "content_hash": f"hash-secret-{n}",
        "metadata": {"raw_payload": "SHOULD-NOT-LEAK"},
    }
    row.update(overrides)
    return row


@pytest_asyncio.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    async with engine.connect() as conn:
        outer = await conn.begin()
        s = AsyncSession(
            bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False
        )
        try:
            yield s
        finally:
            await s.close()
            await outer.rollback()


@pytest_asyncio.fixture
async def client(
    session: AsyncSession, test_settings: Settings
) -> AsyncIterator[httpx.AsyncClient]:
    """App whose session dependency is the rolled-back test session (shadows the root client)."""
    app = create_app(test_settings, manage_db=False)

    async def _session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = _session
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


@pytest_asyncio.fixture
async def seeded(session: AsyncSession) -> None:
    events = EventRepository(session)
    world = WorldRepository(session)
    for key in SEED:
        await events.insert(_values(key))
    for n in (1, 2, 3):
        await world.add_source(eid("geo"), _source(n))
    await world.update_event_scores(
        eid("geo"),
        severity=0.9,
        novelty=0.5,
        corroboration=0.2,
        confidence=0.7,
        economic_channels={},
        source_count=3,
        independent_source_count=2,
        revision=2,
    )
    await session.commit()


async def _get(client: httpx.AsyncClient, path: str = "/api/v1/events", **params: Any) -> Any:
    return await client.get(path, params={**WINDOW, "limit": 200, **params})


async def _ids(client: httpx.AsyncClient, **params: Any) -> tuple[set[str], dict[str, Any]]:
    response = await _get(client, **params)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == len(body["items"])  # window keeps everything on one page
    return {item["id"] for item in body["items"]}, body


def _keys(*names: str) -> set[str]:
    return {eid(n) for n in names}


# -- event JSON ---------------------------------------------------------------------------


@needs_db
async def test_event_json_gains_evidence_fields(client: httpx.AsyncClient, seeded: None) -> None:
    response = await client.get(f"/api/v1/events/{eid('geo')}")
    assert response.status_code == 200
    body = response.json()
    assert body["revision"] == 2
    assert body["source_count"] == 3
    assert body["independent_source_count"] == 2
    assert body["updated_at"] is not None
    assert body["updated_at"].endswith("Z") or "+" in body["updated_at"]
    plain = (await client.get(f"/api/v1/events/{eid('tech')}")).json()
    assert (plain["revision"], plain["source_count"], plain["independent_source_count"]) == (
        1,
        1,
        1,
    )
    assert plain["updated_at"] is None
    listed = (await _get(client)).json()["items"][0]
    assert {"revision", "updated_at", "source_count", "independent_source_count"} <= set(listed)


# -- /events filters ----------------------------------------------------------------------


@needs_db
async def test_window_alone_returns_everything_newest_first(
    client: httpx.AsyncClient, seeded: None
) -> None:
    ids, body = await _ids(client)
    assert ids == _keys(*SEED)
    order = [item["id"] for item in body["items"]]
    assert order[0] == eid("sanction") and order[-1] == eid("geo")


@needs_db
async def test_severity_min_alone_is_inclusive(client: httpx.AsyncClient, seeded: None) -> None:
    ids, body = await _ids(client, severity_min=0.7)
    assert ids == _keys("geo", "energy", "shock", "sanction")
    assert body["total"] == 4
    assert (await _ids(client, severity_min=0))[0] == _keys(*SEED)
    assert (await _ids(client, severity_min=1))[0] == set()


@needs_db
async def test_start_and_end_alone_are_inclusive(client: httpx.AsyncClient, seeded: None) -> None:
    lo = (T0 + timedelta(hours=2)).isoformat().replace("+00:00", "Z")
    hi = (T0 + timedelta(hours=4)).isoformat().replace("+00:00", "Z")
    only_start = await _ids(client, start=lo)
    assert only_start[0] == _keys("supply", "tech", "macro", "other", "shock", "sanction")
    only_end = await _ids(client, end=hi)
    assert only_end[0] == _keys("geo", "energy", "supply", "tech", "macro")
    both = await _ids(client, start=lo, end=hi)
    assert both[0] == _keys("supply", "tech", "macro")
    # An offset that equals the same instant selects the same rows.
    offset = (T0 + timedelta(hours=2)).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    assert (await _ids(client, start=offset, end=hi))[0] == both[0]


@needs_db
@pytest.mark.parametrize(
    ("category", "expected"),
    [
        ("geopolitics", ("geo", "sanction")),
        ("energy", ("energy",)),
        ("supply_chain", ("supply",)),
        ("technology", ("tech",)),
        ("macro", ("macro",)),
        ("other", ("other",)),
    ],
)
async def test_category_alone_excludes_market_shocks(
    client: httpx.AsyncClient, seeded: None, category: str, expected: tuple[str, ...]
) -> None:
    ids, body = await _ids(client, category=category)
    assert ids == _keys(*expected)
    assert body["total"] == len(expected)
    assert eid("shock") not in ids


@needs_db
async def test_filters_combine_with_and(client: httpx.AsyncClient, seeded: None) -> None:
    ids, body = await _ids(client, category="geopolitics", severity_min=0.92)
    assert ids == _keys("sanction") and body["total"] == 1
    assert (await _ids(client, category="geopolitics", event_type="sanction"))[0] == _keys(
        "sanction"
    )
    assert (await _ids(client, category="energy", event_type="sanction"))[0] == set()
    assert (await _ids(client, source_type="market"))[0] == _keys("shock")
    assert (await _ids(client, source_type="market", category="other"))[0] == set()
    assert (await _ids(client, source_type="WORLD", severity_min=0.6))[0] == _keys(
        "geo", "energy", "macro", "sanction"
    )
    start = (T0 + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    assert (await _ids(client, category="geopolitics", start=start, severity_min=0.5))[0] == _keys(
        "sanction"
    )


@needs_db
async def test_total_reflects_filters_with_paging(client: httpx.AsyncClient, seeded: None) -> None:
    response = await _get(client, severity_min=0.5, limit=2, offset=1)
    body = response.json()
    assert body["total"] == 6  # geo, energy, supply, macro, shock, sanction
    assert len(body["items"]) == 2 and body["limit"] == 2 and body["offset"] == 1


@needs_db
@pytest.mark.parametrize(
    "params",
    [
        {"severity_min": -0.1},
        {"severity_min": 1.1},
        {"severity_min": "high"},
        {"severity_min": "nan"},
        {"start": "2031-03-01T00:00:00"},
        {"end": "2031-03-01T00:00:00"},
        {"start": "2031-03-01"},
        {"start": "garbage"},
        {"start": "2031-03-02T00:00:00Z", "end": "2031-03-01T00:00:00Z"},
        {"category": "weather"},
        {"category": "market_shock"},
        {"category": "Geopolitics"},
    ],
)
async def test_invalid_filters_return_422_envelope(
    client: httpx.AsyncClient, params: dict[str, Any]
) -> None:
    response = await client.get("/api/v1/events", params=params)
    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] and error["request_id"]


# -- /events/{id}/sources -----------------------------------------------------------------


@needs_db
async def test_sources_ordering_independence_and_no_leaks(
    client: httpx.AsyncClient, seeded: None
) -> None:
    response = await client.get(f"/api/v1/events/{eid('geo')}/sources")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert [s["source_name"] for s in body["items"]] == ["Outlet 1", "Outlet 2", "Outlet 3"]
    assert [s["is_independent"] for s in body["items"]] == [True, False, True]
    first, second, third = body["items"]
    assert set(first) == {
        "provider",
        "source_name",
        "source_group",
        "source_url",
        "headline",
        "published_at",
        "retrieved_at",
        "is_independent",
        "syndicated_from",
        "reliability",
    }
    assert first["reliability"] == 0.9 and third["reliability"] is None
    assert second["syndicated_from"] == "Outlet 1" and first["syndicated_from"] is None
    assert first["source_url"] == "https://example.test/1"
    assert first["provider"] == "replay" and first["source_group"] == "wire"
    assert first["published_at"].startswith("2031-03-01T10:01:00")
    assert first["retrieved_at"].startswith("2031-03-01T10:01:30")
    text = response.text
    assert "hash-secret" not in text and "SHOULD-NOT-LEAK" not in text
    assert "content_hash" not in text and "metadata" not in text


@needs_db
async def test_sources_empty_for_event_without_evidence(
    client: httpx.AsyncClient, seeded: None
) -> None:
    response = await client.get(f"/api/v1/events/{eid('tech')}/sources")
    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0}


@needs_db
async def test_sources_unknown_event_is_404_envelope(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/events/evt_d3api_missing/sources")
    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "not_found" and error["request_id"]


# -- /world/status ------------------------------------------------------------------------


class FakeRuntime:
    def __init__(
        self,
        mode: WorldMode,
        provider: WorldProviderName = WorldProviderName.WORLD_MONITOR,
        state: WorldProviderState = WorldProviderState.HEALTHY,
        analyzer: str = "AVAILABLE",
        counters: dict[str, Any] | None = None,
    ) -> None:
        self.mode = mode
        self._provider = provider
        self._state = state
        self.analyzer_status = analyzer
        self._counters = counters or {
            "received": 10,
            "created": 6,
            "merged": 2,
            "duplicates": 1,
            "rejected": 1,
            "last_event_at": T0,
        }

    def health(self) -> WorldProviderHealth:
        return WorldProviderHealth(
            provider=self._provider,
            configured=True,
            state=self._state,
            mode=self.mode,
            events_received=10,
            last_event_at=T0,
        )

    def counters(self) -> dict[str, Any]:
        return dict(self._counters)


@pytest_asyncio.fixture
async def status_client() -> AsyncIterator[tuple[httpx.AsyncClient, Any]]:
    app = create_app(Settings(_env_file=None, log_level="WARNING"), manage_db=False)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http, app


async def test_status_without_runtime_is_offline(status_client: Any) -> None:
    client, _ = status_client
    response = await client.get("/api/v1/world/status")
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "OFFLINE"
    assert body["provider"]["state"] == "UNCONFIGURED"
    assert body["provider"]["configured"] is False
    assert body["provider"]["mode"] == "OFFLINE"
    assert body["text_analyzer"] == "DISABLED"
    assert body["counters"]["received"] == 0 and body["counters"]["rejected"] == 0
    assert all(v in (0, None) for v in body["counters"].values())


async def test_status_live_runtime(status_client: Any) -> None:
    client, app = status_client
    app.state.world_runtime = FakeRuntime(WorldMode.LIVE)
    body = (await client.get("/api/v1/world/status")).json()
    assert body["mode"] == "LIVE"
    assert body["provider"]["provider"] == "world_monitor"
    assert body["provider"]["state"] == "HEALTHY" and body["provider"]["mode"] == "LIVE"
    assert body["provider"]["events_received"] == 10
    assert body["counters"]["created"] == 6 and body["counters"]["merged"] == 2
    assert body["counters"]["last_event_at"].startswith("2031-03-01T10:00:00")
    assert body["text_analyzer"] == "AVAILABLE"


async def test_status_replay_runtime(status_client: Any) -> None:
    client, app = status_client
    app.state.world_runtime = FakeRuntime(
        WorldMode.REPLAY, WorldProviderName.REPLAY, WorldProviderState.REPLAY, analyzer="LOADING"
    )
    body = (await client.get("/api/v1/world/status")).json()
    assert body["mode"] == "REPLAY" and body["provider"]["mode"] == "REPLAY"
    assert body["provider"]["provider"] == "replay"
    assert body["text_analyzer"] == "LOADING"


async def test_status_offline_runtime(status_client: Any) -> None:
    client, app = status_client
    app.state.world_runtime = FakeRuntime(
        WorldMode.OFFLINE,
        state=WorldProviderState.UNCONFIGURED,
        analyzer="DISABLED",
        counters={"received": 0},
    )
    body = (await client.get("/api/v1/world/status")).json()
    assert body["mode"] == "OFFLINE" and body["provider"]["state"] == "UNCONFIGURED"
    assert body["counters"] == {"received": 0}


@pytest.mark.parametrize("state", [WorldProviderState.HEALTHY, WorldProviderState.REPLAY])
async def test_replay_provider_is_never_reported_live(
    status_client: Any, state: WorldProviderState
) -> None:
    client, app = status_client
    app.state.world_runtime = FakeRuntime(WorldMode.LIVE, WorldProviderName.REPLAY, state)
    body = (await client.get("/api/v1/world/status")).json()
    assert body["mode"] == "REPLAY"
    assert body["provider"]["mode"] == "REPLAY"


async def test_status_unknown_analyzer_value_is_unavailable(status_client: Any) -> None:
    client, app = status_client
    app.state.world_runtime = FakeRuntime(WorldMode.LIVE, analyzer="bogus")
    assert (await client.get("/api/v1/world/status")).json()["text_analyzer"] == "UNAVAILABLE"
