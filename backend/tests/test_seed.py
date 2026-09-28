import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.fixtures.mock_events import MOCK_HORMUZ_EVENT_ID
from app.services.seed import seed_mock_events


async def test_seed_creates_mock_event_and_is_idempotent(
    engine: AsyncEngine, client: httpx.AsyncClient
) -> None:
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        first = await seed_mock_events(session)
    assert first == {MOCK_HORMUZ_EVENT_ID: "created"}

    async with factory() as session:
        second = await seed_mock_events(session)
    assert second == {MOCK_HORMUZ_EVENT_ID: "skipped"}

    async with engine.connect() as conn:
        count = (await conn.execute(text("SELECT count(*) FROM canonical_events"))).scalar_one()
    assert count == 1

    body = (await client.get(f"/api/v1/events/{MOCK_HORMUZ_EVENT_ID}")).json()
    assert body["title"] == "Strait of Hormuz — Increased Naval Activity"
    assert body["source_type"] == "world"
    assert body["event_type"] == "geopolitical_shipping_disruption"
    assert body["timestamp"] == "2026-09-20T17:00:00Z"
    assert (body["severity"], body["novelty"]) == (0.88, 0.74)
    assert (body["corroboration"], body["confidence"]) == (0.91, 0.91)
    assert body["entities"] == ["Strait of Hormuz"]
    assert body["locations"] == ["Middle East"]
    assert body["economic_channels"] == {
        "oil_supply": -0.82,
        "shipping_costs": 0.77,
        "energy_prices": 0.73,
        "global_trade": -0.61,
    }
    assert body["is_mock"] is True
    assert body["metadata"]["fixture"] == "mock"
    assert body["source_refs"] == [{"name": "World Monitor (mock fixture)", "url": None}]
