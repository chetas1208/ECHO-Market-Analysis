"""Backfill due immutable actual observations for a forecast vintage."""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import get_settings
from app.db.session import create_engine
from app.forecasting.actuals import ForecastActualCollector


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--forecast-id", required=True, type=uuid.UUID)
    result.add_argument("--as-of", required=True, dest="as_of")
    return result


async def run(forecast_id: uuid.UUID, as_of: str) -> int:
    parsed = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("--as-of must be timezone-aware")
    engine = create_engine(get_settings())
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            count = await ForecastActualCollector(session).collect_due(
                forecast_id, as_of=parsed.astimezone(UTC)
            )
    finally:
        await engine.dispose()
    print(f"appended_actuals={count}")
    return 0


if __name__ == "__main__":
    args = parser().parse_args()
    sys.exit(asyncio.run(run(args.forecast_id, args.as_of)))
