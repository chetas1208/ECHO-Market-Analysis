from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.market.providers.base import MarketDataProvider
from app.market.providers.replay import ReplayMarketDataProvider
from app.market.types import Bar, DataMode, ProviderName, ProviderState

T0 = datetime(2025, 3, 3, 14, 30, tzinfo=UTC)


def mk(symbol: str, minute: int, source: ProviderName = ProviderName.MASSIVE) -> Bar:
    return Bar(
        symbol=symbol,
        timestamp=T0 + timedelta(minutes=minute),
        open=10.0,
        high=11.0,
        low=9.0,
        close=10.5,
        volume=100.0,
        source=source,
    )


def make_bars() -> list[Bar]:
    # deliberately shuffled
    return [mk("SPY", 1), mk("NVDA", 0), mk("SPY", 0), mk("NVDA", 1), mk("NVDA", 3)]


async def collect(p: ReplayMarketDataProvider) -> list[Bar]:
    return [b async for b in p.stream()]


def test_is_market_data_provider() -> None:
    assert isinstance(ReplayMarketDataProvider([]), MarketDataProvider)


async def test_order_is_deterministic_timestamp_then_symbol() -> None:
    a = await collect(ReplayMarketDataProvider(make_bars()))
    b = await collect(ReplayMarketDataProvider(list(reversed(make_bars()))))
    got = [(x.timestamp, x.symbol) for x in a]
    assert got == sorted(got)
    assert [(x.symbol, x.timestamp) for x in a] == [(x.symbol, x.timestamp) for x in b]
    assert [x.symbol for x in a[:2]] == ["NVDA", "SPY"]


async def test_source_replay_received_at_and_utc() -> None:
    out = await collect(ReplayMarketDataProvider(make_bars()))
    assert out
    for bar in out:
        assert bar.source == ProviderName.REPLAY
        assert bar.received_at == bar.timestamp
        assert bar.timestamp.utcoffset() == timedelta(0)
        assert bar.received_at is not None and bar.received_at.utcoffset() == timedelta(0)


async def test_lifecycle_states() -> None:
    p = ReplayMarketDataProvider(make_bars())
    assert p.health().state == ProviderState.DISCONNECTED
    await p.connect()
    assert p.health().state == ProviderState.CONNECTED
    await p.disconnect()
    assert p.health().state == ProviderState.DISCONNECTED
    await p.disconnect()  # idempotent
    assert p.health().state == ProviderState.DISCONNECTED
    await p.connect()
    assert p.health().state == ProviderState.CONNECTED


async def test_disconnect_stops_stream() -> None:
    p = ReplayMarketDataProvider(make_bars())
    await p.connect()
    got = []
    async for bar in p.stream():
        got.append(bar)
        await p.disconnect()
    assert len(got) == 1
    assert not p.finished


async def test_end_of_replay_finished_flag() -> None:
    p = ReplayMarketDataProvider(make_bars())
    await p.connect()
    assert not p.finished
    out = await collect(p)
    assert len(out) == 5
    assert p.finished
    assert await collect(p) == []  # nothing more after the end


async def test_empty_replay_finishes() -> None:
    p = ReplayMarketDataProvider([])
    assert await collect(p) == []
    assert p.finished


async def test_subscribe_filtering() -> None:
    p = ReplayMarketDataProvider(make_bars())
    assert p.health().subscribed_symbols == ["NVDA", "SPY"]  # default: all
    await p.subscribe(["nvda"])
    assert p.health().subscribed_symbols == ["NVDA"]
    out = await collect(p)
    assert {b.symbol for b in out} == {"NVDA"}
    assert len(out) == 3


async def test_unsubscribe_filtering() -> None:
    p = ReplayMarketDataProvider(make_bars())
    await p.unsubscribe(["NVDA"])
    out = await collect(p)
    assert {b.symbol for b in out} == {"SPY"}


async def test_fail_after_and_resume_no_repeat_no_skip() -> None:
    p = ReplayMarketDataProvider(make_bars(), fail_after=2)
    await p.connect()
    first: list[Bar] = []
    with pytest.raises(ConnectionError):
        async for bar in p.stream():
            first.append(bar)
    assert len(first) == 2
    assert p.health().state == ProviderState.DISCONNECTED
    assert p.health().last_error
    assert not p.finished

    await p.connect()
    assert p.health().reconnect_attempts == 1
    rest = await collect(p)
    assert p.finished
    combined = [(b.symbol, b.timestamp) for b in first + rest]
    expected = [
        (b.symbol, b.timestamp) for b in await collect(ReplayMarketDataProvider(make_bars()))
    ]
    assert combined == expected


async def test_fail_after_zero_fails_immediately_then_resumes() -> None:
    p = ReplayMarketDataProvider(make_bars(), fail_after=0)
    with pytest.raises(ConnectionError):
        await collect(p)
    await p.connect()
    assert len(await collect(p)) == 5


async def test_speed_sleeps_proportional_to_gaps() -> None:
    slept: list[float] = []

    async def fake_sleep(s: float) -> None:
        slept.append(s)

    p = ReplayMarketDataProvider(make_bars(), speed=60.0, sleep=fake_sleep)
    await collect(p)
    # timestamps: 0,0,1,1,3 minutes -> gaps of 60s, 120s at speed 60 -> 1s, 2s
    assert slept == [1.0, 2.0]


async def test_speed_zero_never_sleeps() -> None:
    slept: list[float] = []

    async def fake_sleep(s: float) -> None:
        slept.append(s)

    await collect(ReplayMarketDataProvider(make_bars(), speed=0.0, sleep=fake_sleep))
    assert slept == []


def test_negative_speed_rejected() -> None:
    with pytest.raises(ValueError):
        ReplayMarketDataProvider([], speed=-1.0)


async def test_health_fields() -> None:
    p = ReplayMarketDataProvider(make_bars())
    h0 = p.health()
    assert h0.provider == ProviderName.REPLAY
    assert h0.mode == DataMode.REPLAY
    assert h0.configured is True
    assert h0.last_message_at is None
    assert h0.messages_received == 0
    await p.connect()
    await collect(p)
    h = p.health()
    assert h.messages_received == 5
    assert h.last_message_at == T0 + timedelta(minutes=3)
    assert h.state == ProviderState.CONNECTED
    assert h.mode == DataMode.REPLAY
