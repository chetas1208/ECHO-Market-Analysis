"""DB tests: GET /events source_type/event_type filters and EventService.create_if_absent.

Requires TEST_DATABASE_URL (name ending ``_test``); the market conftest disables the
default table cleanup, so this module cleans its own rows.
"""

import httpx
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.schemas.event import EventCreate
from app.services.events import EventService
from tests.conftest import event_payload, unique_event_id


@pytest_asyncio.fixture(autouse=True)
async def _clean_events(engine: AsyncEngine):
    async def clean() -> None:
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM canonical_events"))

    await clean()
    yield
    await clean()


async def _post(client: httpx.AsyncClient, minute: int, **overrides: object) -> str:
    event_id = unique_event_id("flt")
    payload = event_payload(id=event_id, timestamp=f"2026-09-20T10:{minute:02d}:00Z", **overrides)
    response = await client.post("/api/v1/events", json=payload)
    assert response.status_code == 201, response.text
    return event_id


@pytest_asyncio.fixture
async def seeded(client: httpx.AsyncClient) -> dict[str, str]:
    return {
        "world_a": await _post(client, 1, source_type="world", event_type="supply_disruption"),
        "world_b": await _post(client, 2, source_type="world", event_type="policy_change"),
        "market_shock": await _post(client, 3, source_type="market", event_type="market_shock"),
        "market_other": await _post(
            client, 4, source_type="market", event_type="supply_disruption"
        ),
        "fin": await _post(client, 5, source_type="financial", event_type="earnings"),
    }


async def _ids(client: httpx.AsyncClient, **params: object) -> tuple[list[str], dict]:
    response = await client.get("/api/v1/events", params=params)
    assert response.status_code == 200, response.text
    body = response.json()
    return [item["id"] for item in body["items"]], body


async def test_unfiltered_unchanged(client: httpx.AsyncClient, seeded: dict[str, str]) -> None:
    ids, body = await _ids(client)
    assert body["total"] == 5
    assert ids == [
        seeded["fin"],
        seeded["market_other"],
        seeded["market_shock"],
        seeded["world_b"],
        seeded["world_a"],
    ]


async def test_filter_by_source_type_and_total(
    client: httpx.AsyncClient, seeded: dict[str, str]
) -> None:
    ids, body = await _ids(client, source_type="market")
    assert ids == [seeded["market_other"], seeded["market_shock"]]
    assert body["total"] == 2
    assert all(item["source_type"] == "market" for item in body["items"])

    ids, body = await _ids(client, source_type="market", limit=1)
    assert ids == [seeded["market_other"]]
    assert body["total"] == 2 and body["limit"] == 1


async def test_source_type_case_insensitive(
    client: httpx.AsyncClient, seeded: dict[str, str]
) -> None:
    lower, _ = await _ids(client, source_type="financial")
    upper, body = await _ids(client, source_type="FINANCIAL")
    mixed, _ = await _ids(client, source_type="Financial")
    assert lower == upper == mixed == [seeded["fin"]]
    assert body["total"] == 1


async def test_filter_by_event_type(client: httpx.AsyncClient, seeded: dict[str, str]) -> None:
    ids, body = await _ids(client, event_type="supply_disruption")
    assert ids == [seeded["market_other"], seeded["world_a"]]
    assert body["total"] == 2

    ids, body = await _ids(client, event_type="nope")
    assert ids == [] and body["total"] == 0


async def test_filter_by_both(client: httpx.AsyncClient, seeded: dict[str, str]) -> None:
    ids, body = await _ids(client, source_type="market", event_type="supply_disruption")
    assert ids == [seeded["market_other"]]
    assert body["total"] == 1

    ids, body = await _ids(client, source_type="market", event_type="market_shock")
    assert ids == [seeded["market_shock"]]

    ids, body = await _ids(client, source_type="world", event_type="market_shock")
    assert ids == [] and body["total"] == 0


async def test_invalid_source_type_is_422_envelope(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/events", params={"source_type": "bogus"})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["request_id"]


async def test_create_if_absent_duplicate(engine: AsyncEngine) -> None:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    event_id = unique_event_id("cia")
    payload = EventCreate.model_validate(event_payload(id=event_id, title="first"))
    dupe = EventCreate.model_validate(event_payload(id=event_id, title="second"))

    async with factory() as session:
        event, created = await EventService(session).create_if_absent(payload)
        assert created is True and event.id == event_id

    async with factory() as session:
        existing, created = await EventService(session).create_if_absent(dupe)
        assert created is False
        assert existing.id == event_id and existing.title == "first"

    async with factory() as session:
        _, total = await EventService(session).list(limit=10, offset=0)
        assert total == 1


async def test_create_if_absent_without_id_always_creates(engine: AsyncEngine) -> None:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    payload = EventCreate.model_validate(event_payload())
    async with factory() as session:
        service = EventService(session)
        first, c1 = await service.create_if_absent(payload)
        second, c2 = await service.create_if_absent(payload)
    assert c1 and c2 and first.id != second.id


async def test_post_duplicate_still_409(client: httpx.AsyncClient) -> None:
    payload = event_payload(id=unique_event_id("dup"))
    assert (await client.post("/api/v1/events", json=payload)).status_code == 201
    dup = await client.post("/api/v1/events", json=payload)
    assert dup.status_code == 409
    assert dup.json()["error"]["code"] == "conflict"
