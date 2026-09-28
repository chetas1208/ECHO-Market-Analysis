from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.repositories.events import EventRepository


async def test_candidate_retrieval_excludes_post_cutoff_and_market_events(
    engine: AsyncEngine,
) -> None:
    now = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        repository = EventRepository(session)
        values = {
            "summary": "test",
            "entities": [],
            "companies": [],
            "locations": [],
            "economic_channels": {"semiconductor_supply": -0.8},
            "severity": 0.8,
            "novelty": 0.8,
            "corroboration": 0.8,
            "confidence": 0.8,
            "source_refs": [],
            "metadata_": {},
            "is_mock": True,
        }
        await repository.insert(
            {
                **values,
                "id": "evt_cutoff_shock",
                "timestamp": now,
                "source_type": "MARKET",
                "event_type": "market_shock",
                "title": "shock",
                "ingested_at": now,
            }
        )
        await repository.insert(
            {
                **values,
                "id": "evt_cutoff_visible",
                "timestamp": now - timedelta(minutes=5),
                "source_type": "WORLD",
                "event_type": "natural_disaster",
                "title": "visible",
                "ingested_at": now - timedelta(minutes=1),
            }
        )
        await repository.insert(
            {
                **values,
                "id": "evt_cutoff_future_ingest",
                "timestamp": now - timedelta(minutes=4),
                "source_type": "WORLD",
                "event_type": "natural_disaster",
                "title": "future ingest",
                "ingested_at": now + timedelta(minutes=1),
            }
        )
        await session.commit()
        candidates = await repository.list_cause_candidates(
            now - timedelta(hours=1),
            now,
            now,
            exclude_event_id="evt_cutoff_shock",
        )
        assert [event.id for event in candidates] == ["evt_cutoff_visible"]
