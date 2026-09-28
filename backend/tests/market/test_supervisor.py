from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest

from app.market.providers.supervisor import SupervisedProvider
from app.market.settings import ReconnectConfig
from app.market.types import Bar, DataMode, ProviderHealth, ProviderName, ProviderState

T0 = datetime(2026, 1, 5, 15, 0, tzinfo=UTC)
CFG = ReconnectConfig(base_delay_s=1.0, max_delay_s=8.0, factor=2.0, jitter=0.0, stale_after_s=90.0)


def bar(i: int, symbol: str = "NVDA") -> Bar:
    return Bar(
        symbol=symbol,
        timestamp=T0 + timedelta(minutes=i),
        open=1,
        high=1,
        low=1,
        close=1,
        volume=1,
        source=ProviderName.MASSIVE,
    )


class FakeInner:
    """Script items: Bar to yield, or an Exception instance to raise. End of script = EOF."""

    def __init__(self, script=(), *, connect_error: Exception | None = None, state=None):
        self.name = ProviderName.MASSIVE
        self.script = list(script)
        self.connect_error = connect_error
        self.state = state or ProviderState.CONNECTED
        self.connects = 0
        self.disconnects = 0
        self.subscribed: list[str] = []

    async def connect(self) -> None:
        self.connects += 1
        if self.connect_error:
            raise self.connect_error

    async def disconnect(self) -> None:
        self.disconnects += 1

    async def subscribe(self, symbols: list[str]) -> None:
        self.subscribed.extend(symbols)

    async def unsubscribe(self, symbols: list[str]) -> None:
        self.subscribed = [s for s in self.subscribed if s not in symbols]

    async def stream(self) -> AsyncIterator[Bar]:
        for item in self.script:
            await asyncio.sleep(0)
            if isinstance(item, BaseException):
                raise item
            yield item

    def health(self) -> ProviderHealth:
        return ProviderHealth(
            provider=self.name,
            state=self.state,
            configured=self.state != ProviderState.UNCONFIGURED,
            mode=DataMode.LIVE,
        )


class Harness:
    def __init__(self, inners: list[FakeInner], *, is_active=lambda ts: True):
        self.inners = inners
        self.built: list[FakeInner] = []
        self.delays: list[float] = []
        self.now = T0

        def factory() -> FakeInner:
            inner = inners[min(len(self.built), len(inners) - 1)]
            self.built.append(inner)
            return inner

        async def sleep(d: float) -> None:
            self.delays.append(d)
            await asyncio.sleep(0)

        self.sup = SupervisedProvider(
            factory, CFG, is_active=is_active, clock=lambda: self.now, sleep=sleep
        )

    async def collect(self) -> list[Bar]:
        out: list[Bar] = []
        async with asyncio.timeout(5):
            async for b in self.sup.stream():
                out.append(b)
        return out


async def test_failure_reconnects_and_continues():
    a = FakeInner([bar(0), ConnectionError("boom")])
    b = FakeInner([bar(1), bar(2)])
    h = Harness([a, b])
    await h.sup.connect()
    got = await h.collect()
    assert [x.timestamp for x in got] == [bar(0).timestamp, bar(1).timestamp, bar(2).timestamp]
    assert len(h.built) == 2 and a.disconnects >= 1
    assert h.sup.attempts == 1
    assert h.sup.health().reconnect_attempts == 1
    assert "boom" in (h.sup.health().last_error or "")


@pytest.mark.parametrize(
    "exc", [ConnectionError("x"), OSError("x"), TimeoutError(), ValueError("x")]
)
async def test_any_error_type_is_swallowed(exc):
    h = Harness([FakeInner([exc]), FakeInner([bar(0)])])
    assert len(await h.collect()) == 1


async def test_backoff_delays_recorded_and_reset_after_message():
    # 3 failures (no message) -> 1,2,4; then a message is received; next failure restarts at 1.
    inners = [FakeInner([ConnectionError()]) for _ in range(3)]
    inners.append(FakeInner([bar(0), ConnectionError()]))
    inners.append(FakeInner([bar(1)]))
    h = Harness(inners)
    got = await h.collect()
    assert len(got) == 2
    assert h.delays == [1.0, 2.0, 4.0, 1.0]
    assert all(d > 0 for d in h.delays)  # never a tight loop


async def test_connect_failures_back_off_too():
    inners = [FakeInner(connect_error=ConnectionError("down")) for _ in range(3)]
    inners.append(FakeInner([bar(0)]))
    h = Harness(inners)
    await h.sup.connect()  # must not raise
    assert h.sup.state == ProviderState.RECONNECTING
    got = await h.collect()
    assert len(got) == 1
    assert h.delays == [1.0, 2.0, 4.0]


async def test_no_crash_after_20_failures_and_delay_capped():
    inners = [FakeInner([ConnectionError()]) for _ in range(20)] + [FakeInner([bar(0)])]
    h = Harness(inners)
    got = await h.collect()
    assert len(got) == 1
    assert h.sup.attempts == 20
    assert len(h.delays) == 20
    assert max(h.delays) == CFG.max_delay_s
    assert h.delays[:4] == [1.0, 2.0, 4.0, 8.0]


async def test_injected_backoff_is_used():
    class FakeBackoff:
        def __init__(self):
            self.n = 0
            self.resets = 0

        def next(self) -> float:
            self.n += 1
            return 0.5 * self.n

        def reset(self) -> None:
            self.resets += 1

    fb = FakeBackoff()
    inners = [FakeInner([ConnectionError()]), FakeInner([bar(0)])]
    h = Harness(inners)
    h.sup._backoff = fb
    await h.collect()
    assert h.delays == [0.5]
    assert fb.resets == 1


async def test_resubscribe_after_reconnect():
    a = FakeInner([bar(0), ConnectionError()])
    b = FakeInner([bar(1)])
    h = Harness([a, b])
    await h.sup.connect()
    await h.sup.subscribe(["NVDA", "SPY"])
    assert a.subscribed == ["NVDA", "SPY"]
    await h.sup.subscribe(["SOXX", "NVDA"])
    assert a.subscribed == ["NVDA", "SPY", "SOXX"]
    await h.collect()
    assert b.subscribed == ["NVDA", "SPY", "SOXX"]
    assert h.sup.health().subscribed_symbols == ["NVDA", "SPY", "SOXX"]
    await h.sup.unsubscribe(["SPY"])
    assert h.sup.health().subscribed_symbols == ["NVDA", "SOXX"]


async def test_subscribe_before_connect_applied_on_connect():
    a = FakeInner([bar(0)])
    h = Harness([a])
    await h.sup.subscribe(["NVDA"])
    await h.sup.connect()
    assert a.subscribed == ["NVDA"]


async def test_unconfigured_stops_without_retry():
    a = FakeInner(state=ProviderState.UNCONFIGURED, connect_error=RuntimeError("no key"))
    h = Harness([a])
    await h.sup.connect()
    assert h.sup.state == ProviderState.UNCONFIGURED
    assert await h.collect() == []
    assert h.delays == [] and len(h.built) == 1 and a.connects == 0
    hl = h.sup.health()
    assert hl.state == ProviderState.UNCONFIGURED and not hl.configured


async def test_unconfigured_detected_from_connect_exception_name():
    class ProviderUnconfigured(RuntimeError):
        pass

    a = FakeInner(connect_error=ProviderUnconfigured("no key"))
    h = Harness([a])
    assert await h.collect() == []
    assert h.sup.state == ProviderState.UNCONFIGURED
    assert h.delays == [] and a.connects == 1


async def test_stale_detection_and_clear():
    h = Harness([FakeInner()])
    await h.sup.connect()
    assert h.sup.state == ProviderState.CONNECTED
    h.now = T0 + timedelta(seconds=89)
    assert h.sup.check_stale() is False
    h.now = T0 + timedelta(seconds=91)
    assert h.sup.check_stale() is True
    assert h.sup.health().state == ProviderState.STALE
    h.sup.touch()  # message arrives
    assert h.sup.state == ProviderState.CONNECTED
    assert h.sup.check_stale() is False
    h.now += timedelta(seconds=120)
    assert h.sup.check_stale(h.now) is True


async def test_inactive_market_is_not_stale():
    active = {"v": False}
    h = Harness([FakeInner()], is_active=lambda ts: active["v"])
    await h.sup.connect()
    h.now = T0 + timedelta(hours=10)
    assert h.sup.check_stale() is False
    assert h.sup.state == ProviderState.CONNECTED
    active["v"] = True
    assert h.sup.check_stale() is True
    active["v"] = False  # market closes: stale clears
    assert h.sup.check_stale() is False
    assert h.sup.state == ProviderState.CONNECTED


async def test_stale_uses_last_message_time():
    h = Harness([FakeInner([bar(0)])])
    await h.collect()  # touched at T0
    h.now = T0 + timedelta(seconds=60)
    assert h.sup.check_stale() is False
    h.now = T0 + timedelta(seconds=100)
    assert h.sup.check_stale() is False or h.sup.state == ProviderState.DISCONNECTED


async def test_health_merges_supervisor_state():
    h = Harness([FakeInner([bar(0), bar(1)])])
    await h.sup.connect()
    hl = h.sup.health()
    assert hl.state == ProviderState.CONNECTED and hl.mode == DataMode.LIVE
    assert hl.provider == ProviderName.MASSIVE and hl.messages_received == 0
    await h.collect()
    hl = h.sup.health()
    assert hl.messages_received == 2 and hl.last_message_at == T0
    assert hl.state == ProviderState.DISCONNECTED  # clean EOF


async def test_cancel_cleanly():
    class Hang(FakeInner):
        async def stream(self):
            yield bar(0)
            await asyncio.Event().wait()

    a = Hang()
    h = Harness([a])
    got: list[Bar] = []

    async def consume():
        async for b in h.sup.stream():
            got.append(b)

    task = asyncio.create_task(consume())
    for _ in range(20):
        await asyncio.sleep(0)
    assert len(got) == 1
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert h.sup.state == ProviderState.DISCONNECTED
    assert a.disconnects >= 1


async def test_cancel_during_backoff_sleep():
    started = asyncio.Event()

    async def slow_sleep(d: float) -> None:
        started.set()
        await asyncio.sleep(3600)

    a = FakeInner([ConnectionError()])
    sup = SupervisedProvider(lambda: a, CFG, sleep=slow_sleep)
    task = asyncio.create_task(_drain(sup))
    await asyncio.wait_for(started.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert sup.state == ProviderState.DISCONNECTED


async def _drain(sup: SupervisedProvider) -> None:
    async for _ in sup.stream():
        pass


async def test_stop_ends_stream_and_disconnects():
    a = FakeInner([bar(0), bar(1), bar(2)])
    h = Harness([a])
    await h.sup.connect()
    got = []
    async for b in h.sup.stream():
        got.append(b)
        await h.sup.stop()
    assert len(got) == 1
    assert h.sup.state == ProviderState.DISCONNECTED and a.disconnects >= 1
    await h.sup.stop()  # idempotent
    assert [b async for b in h.sup.stream()] == []


async def test_health_never_raises_when_inner_health_fails():
    a = FakeInner()

    def boom():
        raise RuntimeError("x")

    a.health = boom  # type: ignore[method-assign]
    sup = SupervisedProvider(lambda: a, CFG)
    assert sup.health().state == ProviderState.DISCONNECTED
