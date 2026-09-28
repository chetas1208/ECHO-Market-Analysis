from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.models import MarketObservation

T0 = datetime(2026, 9, 20, 14, 30, tzinfo=UTC)

INSERT = text(
    """
    INSERT INTO market_observations
        (symbol, timestamp, open, high, low, close, volume, source, timeframe)
    VALUES (:symbol, :ts, :o, :h, :l, :c, :v, :source, COALESCE(:tf, '1m'))
    """
)


def bar(**overrides: object) -> dict:
    params = {
        "symbol": "XOM",
        "ts": T0,
        "o": 100.0,
        "h": 101.0,
        "l": 99.5,
        "c": 100.5,
        "v": 12345,
        "source": "massive",
        "tf": None,
    }
    params.update(overrides)
    return params


async def test_insert_and_defaults(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.execute(INSERT, bar())
        row = (
            await conn.execute(
                text("SELECT timeframe, vwap, trade_count, created_at FROM market_observations")
            )
        ).one()
    assert row.timeframe == "1m"
    assert row.vwap is None and row.trade_count is None
    assert row.created_at is not None


async def test_orm_roundtrip_returns_floats(engine: AsyncEngine) -> None:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        session.add(
            MarketObservation(
                symbol="CVX",
                timestamp=T0,
                open=1.25,
                high=2.5,
                low=1.0,
                close=2.0,
                volume=1000,
                vwap=1.9,
                trade_count=42,
                source="alpaca",
                timeframe="5m",
            )
        )
        await session.commit()
    async with factory() as session:
        row = (await session.execute(select(MarketObservation))).scalar_one()
    assert (row.open, row.high, row.vwap, row.trade_count) == (1.25, 2.5, 1.9, 42)
    assert isinstance(row.open, float)
    assert row.timeframe == "5m"


async def test_duplicate_bar_violates_unique(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.execute(INSERT, bar())
    with pytest.raises(IntegrityError, match="uq_market_observations"):
        async with engine.begin() as conn:
            await conn.execute(INSERT, bar())


async def test_append_is_idempotent_with_on_conflict(engine: AsyncEngine) -> None:
    upsert = text(
        str(INSERT) + " ON CONFLICT ON CONSTRAINT "
        "uq_market_observations_symbol_timestamp_source_timeframe DO NOTHING"
    )
    async with engine.begin() as conn:
        for _ in range(3):
            await conn.execute(upsert, bar())
        count = (await conn.execute(text("SELECT count(*) FROM market_observations"))).scalar_one()
    assert count == 1


async def test_same_bar_allowed_across_source_timeframe_symbol_and_time(
    engine: AsyncEngine,
) -> None:
    variants = [
        bar(),
        bar(source="alpaca"),
        bar(tf="5m"),
        bar(tf="15m"),
        bar(symbol="CVX"),
        bar(ts=T0 + timedelta(minutes=1)),
    ]
    async with engine.begin() as conn:
        for params in variants:
            await conn.execute(INSERT, params)
        count = (await conn.execute(text("SELECT count(*) FROM market_observations"))).scalar_one()
    assert count == len(variants)


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"h": 99.0}, "high_low"),  # high < low
        ({"o": 102.0}, "ohlc_within_range"),  # open above high
        ({"c": 98.0}, "ohlc_within_range"),  # close below low
        ({"v": -1}, "volume_nonneg"),
        ({"o": -1.0, "l": -2.0}, "prices_nonneg"),
        ({"tf": "weekly"}, "timeframe_format"),
        ({"symbol": " "}, "symbol_nonempty"),
    ],
)
async def test_check_constraints(engine: AsyncEngine, overrides: dict, constraint: str) -> None:
    with pytest.raises(IntegrityError, match=constraint):
        async with engine.begin() as conn:
            await conn.execute(INSERT, bar(**overrides))
