"""Validate the checked-in graph seed and create an immutable database snapshot."""

from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import get_settings
from app.db.session import create_engine
from app.graph.seed import load_seed
from app.graph.service import ShockGraphService


async def main() -> None:
    load_seed()
    settings = get_settings()
    engine = create_engine(settings)
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            snapshot = await ShockGraphService(session).create_seed_snapshot()
            print(
                f"snapshot_id={snapshot.snapshot_id} graph_version={snapshot.graph_version} "
                f"nodes={snapshot.node_count} edges={snapshot.edge_count} "
                f"content_hash={snapshot.content_hash}"
            )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
