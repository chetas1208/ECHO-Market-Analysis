"""MarketPipeline tests: fake providers, sinks and writers; no network, no database.

The only test that uses the real feature engine + detector is the replay-over-scenario one.
Everything else stubs them so the tests stay fast and deterministic.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable, Sequence
from datetime import UTC, datetime, timedelta

import pytest

from app.market.fixtures import build_shock_scenario
from app.market.pipeline import MarketPipeline
from app.market.providers.replay import ReplayMarketDataProvider
from app.market.settings import FeatureConfig, MarketSettings
from app.market.shock.detector import ShockDecision
from app.market.types import (
    Bar,
    DataMode,
    FeatureStatus,
    Interval,
    ProviderHealth,
    ProviderName,
    ProviderState,
    ShockAssessment,
    ShockDirection,
    ShockLevel,
    SymbolFeatures,
)
from app.market.universe import Universe, UniverseEntry, get_universe
from app.schemas.event import EventCreate

T0 = datetime(2025, 3, 3, 14, 30, tzinfo=UTC)  # Monday 09:30 ET, on a 5m/15m boundary

UNIV = Universe(
    [
        UniverseEntry(symbol="NVDA", group="semis", role="equity", sector_benchmark="SOXX"),
        UniverseEntry(symbol="SOXX", group="semis", role="benchmark"),
        UniverseEntry(symbol="SPY", group="index", role="benchmark"),
    ],
    market_benchmark="SPY",
)


def mk(
    symbol: str,
    minute: int,
    source: ProviderName = ProviderName.MASSIVE,
    close: float | None = None,
    volume: float = 100.0,
) -> Bar:
    c = 100.0 + minute if close is None else close
    return Bar(
        symbol=symbol,
        timestamp=T0 + timedelta(minutes=minute),
        open=c - 0.2,
        high=c + 1.0,
        low=c - 1.0,
        close=c,
        volume=volume,
        source=source,
    )


def triple(minute: int, source: ProviderName = ProviderName.MASSIVE) -> list[Bar]:
    """One minute of the whole (tiny) universe, benchmarks after the equity."""
    return [mk("NVDA", minute, source), mk("SOXX", minute, source), mk("SPY", minute, source)]


def settings(**kw: object) -> MarketSettings:
    return MarketSettings(_env_file=None, **kw)  # type: ignore[arg-type]


class Writer:
    """In-memory stand-in for the batched DB upsert."""

    def __init__(self) -> None:
        self.writes: list[list[Bar]] = []

    async def __call__(self, bars: Sequence[Bar]) -> int:
        self.writes.append(list(bars))
        return len(bars)

    @property
    def bars(self) -> list[Bar]:
        return [b for w in self.writes for b in w]

    def of(self, interval: Interval, symbol: str | None = None) -> list[Bar]:
        return [b for b in self.bars if b.interval == interval and symbol in (None, b.symbol)]


class FakeProvider:
    def __init__(
        self,
        bars: Sequence[Bar] = (),
        name: ProviderName = ProviderName.MASSIVE,
        *,
        error_after: int | None = None,
        connect_error: Exception | None = None,
        subscribe_error: Exception | None = None,
        hang: bool = False,
        state: ProviderState = ProviderState.CONNECTED,
        health_mode: DataMode | None = None,
    ) -> None:
        self.name = name
        self._bars = list(bars)
        self.error_after = error_after
        self.connect_error = connect_error
        self.subscribe_error = subscribe_error
        self.hang = hang
        self.state = state
        self.health_mode = health_mode
        self.malformed = 0
        self.subscribed: list[str] = []
        self.disconnected = False

    async def connect(self) -> None:
        if self.connect_error is not None:
            raise self.connect_error

    async def disconnect(self) -> None:
        self.disconnected = True

    async def subscribe(self, symbols: list[str]) -> None:
        if self.subscribe_error is not None:
            raise self.subscribe_error
        self.subscribed = list(symbols)

    async def unsubscribe(self, symbols: list[str]) -> None:
        return None

    async def stream(self) -> AsyncIterator[Bar]:
        # No awaits between yields on purpose: the producer never suspends, which makes the
        # overflow tests deterministic (the consumer only runs once the producer is done).
        for i, bar in enumerate(self._bars):
            if self.error_after is not None and i >= self.error_after:
                raise RuntimeError("boom")
            yield bar
        if self.error_after is not None and self.error_after >= len(self._bars):
            raise RuntimeError("boom")
        if self.hang:
            await asyncio.Event().wait()

    def health(self) -> ProviderHealth:
        mode = self.health_mode or (
            DataMode.REPLAY if self.name == ProviderName.REPLAY else DataMode.LIVE
        )
        return ProviderHealth(
            provider=self.name,
            state=self.state,
            configured=True,
            mode=mode,
            subscribed_symbols=list(self.subscribed),
            malformed_messages=self.malformed,
        )


class StubEngine:
    """Records what the pipeline hands the feature engine; returns a trivial snapshot."""

    def __init__(self, status: FeatureStatus = FeatureStatus.READY) -> None:
        self.status = status
        self.calls: list[tuple[str, datetime, dict[str, tuple[int, datetime]]]] = []

    def compute(self, symbol: str, frames: dict) -> SymbolFeatures:  # type: ignore[type-arg]
        df = frames[symbol]
        as_of = df["timestamp"][-1]
        self.calls.append(
            (symbol, as_of, {k: (v.height, v["timestamp"][-1]) for k, v in frames.items()})
        )
        return SymbolFeatures(
            symbol=symbol, as_of=as_of, price=float(df["close"][-1]), overall_status=self.status
        )


class StubDetector:
    def __init__(
        self,
        level: Callable[[SymbolFeatures], ShockLevel] = lambda f: ShockLevel.NONE,
        emit: Callable[[SymbolFeatures], bool] = lambda f: False,
    ) -> None:
        self._level = level
        self._emit = emit

    def evaluate(self, f: SymbolFeatures) -> ShockDecision:
        level = self._level(f)
        ready = f.overall_status == FeatureStatus.READY
        a = ShockAssessment(
            symbol=f.symbol,
            as_of=f.as_of,
            score=0.9 if level in (ShockLevel.SHOCK, ShockLevel.SEVERE) else 0.1,
            level=level,
            direction=ShockDirection.NEGATIVE,
            ready=ready,
        )
        emit = ready and self._emit(f)
        return ShockDecision(emit, a, "emit" if emit else "stub")


def make(
    provider: FakeProvider | ReplayMarketDataProvider,
    *,
    writer: Writer | None = None,
    sink: Callable[[EventCreate], object] | None = None,
    engine: object | None = None,
    detector: object | None = None,
    cfg: MarketSettings | None = None,
    **kw: object,
) -> MarketPipeline:
    return MarketPipeline(
        provider,  # type: ignore[arg-type]
        kw.pop("universe", UNIV),  # type: ignore[arg-type]
        cfg or settings(),
        None,
        sink,  # type: ignore[arg-type]
        bar_writer=writer,
        feature_engine=engine or StubEngine(),  # type: ignore[arg-type]
        detector=detector or StubDetector(),  # type: ignore[arg-type]
        **kw,  # type: ignore[arg-type]
    )


async def run(p: MarketPipeline, limit_s: float = 60.0) -> None:
    async with asyncio.timeout(limit_s):
        await p.run()


async def wait_for(cond: Callable[[], bool], limit_s: float = 5.0) -> None:
    end = asyncio.get_running_loop().time() + limit_s
    while not cond():
        assert asyncio.get_running_loop().time() < end, "condition not met in time"
        await asyncio.sleep(0.01)


def records(caplog: pytest.LogCaptureFixture, operation: str) -> list[logging.LogRecord]:
    return [r for r in caplog.records if getattr(r, "operation", None) == operation]


# --------------------------------------------------------------------------- queue


async def test_overflow_drops_oldest_counts_and_stays_bounded(
    caplog: pytest.LogCaptureFixture,
) -> None:
    bars = [mk("SPY", i) for i in range(100)]
    w = Writer()
    p = make(FakeProvider(bars), writer=w, cfg=settings(echo_market_queue_size=10))
    with caplog.at_level(logging.WARNING, logger="echo.market.pipeline"):
        await run(p)
    assert p.stats["received"] == 100
    assert p.dropped == 90
    assert p.stats["accepted"] == 10  # bounded: only queue-size bars survived
    # drop-OLDEST: the survivors are the newest ten bars
    hist = p.history("SPY")
    assert hist is not None
    assert list(hist["timestamp"]) == [T0 + timedelta(minutes=i) for i in range(90, 100)]
    assert p.latest_price("SPY") == (199.0, T0 + timedelta(minutes=99))
    assert p.queue_stats() == {"depth": 0, "capacity": 10, "dropped": 90}
    # rate-limited WARN: 90 drops -> a single warning line
    assert len(records(caplog, "queue_overflow")) == 1


async def test_replay_uses_backpressure_not_drops() -> None:
    bars = [mk("SPY", i, ProviderName.REPLAY) for i in range(100)]
    p = make(
        ReplayMarketDataProvider(bars), writer=Writer(), cfg=settings(echo_market_queue_size=10)
    )
    await run(p)
    assert p.dropped == 0
    assert p.stats["accepted"] == 100
    assert p.replay_finished


# --------------------------------------------------------------------------- dedupe


async def test_cross_provider_dedupe_authoritative_provider_wins() -> None:
    primary = FakeProvider([mk(s, i) for i in range(10) for s in ("SPY", "SOXX")])
    fallback = FakeProvider(
        [mk(s, i, ProviderName.ALPACA) for i in range(10) for s in ("SPY", "SOXX")],
        ProviderName.ALPACA,
    )
    w = Writer()
    p = make(primary, writer=w, fallback=fallback)
    await run(p)
    ones = w.of(Interval.M1)
    assert len(ones) == 20  # every (symbol, minute) exactly once
    assert {b.source for b in w.bars} == {ProviderName.MASSIVE}
    assert p.stats["accepted"] == 20
    assert p.active_provider == ProviderName.MASSIVE


async def test_same_provider_duplicates_are_ignored() -> None:
    bars = [mk("SPY", i) for i in range(5)]
    w = Writer()
    p = make(FakeProvider(bars + bars + bars), writer=w)
    await run(p)
    assert p.stats["received"] == 15
    assert p.stats["accepted"] == 5
    assert len(w.of(Interval.M1)) == 5


async def test_failover_switches_accepted_source(caplog: pytest.LogCaptureFixture) -> None:
    primary = FakeProvider(name=ProviderName.MASSIVE)
    fallback = FakeProvider(name=ProviderName.ALPACA)
    p = make(primary, fallback=fallback)
    await p._process(mk("SPY", 0, ProviderName.MASSIVE))
    assert p.stats["accepted"] == 1
    primary.state = ProviderState.RECONNECTING
    with caplog.at_level(logging.INFO, logger="echo.market.pipeline"):
        p._observe_health()
    assert p.active_provider == ProviderName.ALPACA
    assert records(caplog, "provider_failover")
    await p._process(mk("SPY", 1, ProviderName.MASSIVE))  # no longer authoritative
    await p._process(mk("SPY", 1, ProviderName.ALPACA))
    assert p.stats["accepted"] == 2
    hist = p.history("SPY")
    assert hist is not None and hist.height == 2


# --------------------------------------------------------------------------- aggregation


async def test_5m_and_15m_bars_are_emitted() -> None:
    bars = [mk("SPY", i) for i in range(35)]  # 14:30 .. 15:04
    w = Writer()
    p = make(FakeProvider(bars), writer=w)
    await run(p)
    b5, b15 = w.of(Interval.M5), w.of(Interval.M15)
    assert len(w.of(Interval.M1)) == 35
    assert [b.timestamp for b in b5] == [T0 + timedelta(minutes=5 * k) for k in range(7)]
    assert {b.timestamp for b in b15} == {T0 + timedelta(minutes=15 * k) for k in range(3)}
    first = b5[0]
    assert first.open == bars[0].open and first.close == bars[4].close
    assert first.high == max(b.high for b in bars[:5]) and first.low == min(b.low for b in bars[:5])
    assert first.volume == 500.0
    assert p.stats["aggregated"] == len(b5) + len(b15)


# --------------------------------------------------------------------------- batching


async def test_writes_are_batched_not_per_bar() -> None:
    bars = [mk(s, i) for i in range(500) for s in ("SPY", "SOXX")]  # 1000 1m bars
    w = Writer()
    p = make(FakeProvider(bars), writer=w, batch_size=200, flush_interval_s=60.0, clock=lambda: 0.0)
    await run(p)
    persisted = sum(len(x) for x in w.writes)
    assert persisted == 1000 + p.stats["aggregated"]  # nothing lost
    assert p.stats["persisted"] == persisted
    assert len(w.writes) == p.stats["writes"]
    assert len(w.writes) <= persisted // 200 + 2
    assert len(w.writes) * 20 < 1000  # << one write per bar


async def test_idle_timeout_flushes_partial_batch() -> None:
    w = Writer()
    p = make(
        FakeProvider([mk("SPY", i) for i in range(3)], hang=True),
        writer=w,
        batch_size=10_000,
        flush_interval_s=0.05,
    )
    p.start()
    try:
        await wait_for(lambda: len(w.of(Interval.M1)) == 3)
    finally:
        await p.stop()


async def test_failed_write_is_retried_and_nothing_is_lost() -> None:
    calls: list[int] = []
    stored: list[Bar] = []

    async def flaky(bars: Sequence[Bar]) -> int:
        calls.append(len(bars))
        if len(calls) == 1:
            raise ConnectionError("db down")
        stored.extend(bars)
        return len(bars)

    p = MarketPipeline(
        FakeProvider([mk("SPY", i) for i in range(20)]),
        UNIV,
        settings(),
        None,
        None,
        bar_writer=flaky,
        feature_engine=StubEngine(),
        detector=StubDetector(),
        batch_size=5,
        flush_interval_s=0.01,
    )
    await run(p)
    assert p.stats["write_failures"] >= 1
    assert len([b for b in stored if b.interval == Interval.M1]) == 20


# --------------------------------------------------------------------------- failures


async def test_provider_stream_error_never_propagates_and_data_survives(
    caplog: pytest.LogCaptureFixture,
) -> None:
    w = Writer()
    p = make(FakeProvider([mk("SPY", i) for i in range(5)], error_after=5), writer=w)
    with caplog.at_level(logging.WARNING, logger="echo.market.pipeline"):
        await run(p)  # must not raise
    assert p.finished
    assert len(w.of(Interval.M1)) == 5
    (health,) = p.provider_healths()
    assert health.state == ProviderState.DEGRADED and "boom" in (health.last_error or "")
    assert p.mode == DataMode.OFFLINE
    assert not p.replay_finished
    assert records(caplog, "provider_degraded")


@pytest.mark.parametrize("field", ["connect_error", "subscribe_error"])
async def test_provider_startup_error_keeps_pipeline_alive(field: str) -> None:
    p = make(FakeProvider([mk("SPY", 0)], **{field: OSError("refused")}), writer=Writer())
    await run(p)
    assert p.finished
    assert p.provider_healths()[0].state == ProviderState.DEGRADED
    assert p.stats["accepted"] == 0


async def test_one_failed_provider_does_not_stop_the_other() -> None:
    bad = FakeProvider(connect_error=OSError("refused"), name=ProviderName.MASSIVE)
    good = FakeProvider([mk("SPY", i, ProviderName.ALPACA) for i in range(3)], ProviderName.ALPACA)
    p = make(bad, fallback=good, writer=Writer())
    await run(p)
    assert p.active_provider == ProviderName.ALPACA  # failed over on the first fallback bar
    assert p.stats["received"] == 3
    assert p.stats["accepted"] == 3


async def test_malformed_bar_in_pipeline_does_not_kill_loop() -> None:
    class Exploding(StubEngine):
        def compute(self, symbol: str, frames: dict) -> SymbolFeatures:  # type: ignore[type-arg]
            raise ValueError("engine bug")

    p = make(FakeProvider([b for m in range(4) for b in triple(m)]), engine=Exploding())
    await run(p)  # engine failures are contained
    assert p.stats["errors"] >= 1
    assert p.stats["accepted"] == 12


# --------------------------------------------------------------------------- shutdown


async def test_stop_flushes_everything_buffered() -> None:
    w = Writer()
    prov = FakeProvider([mk("SPY", i) for i in range(6)], hang=True)
    p = make(prov, writer=w, batch_size=10_000, flush_interval_s=3600.0)
    p.start()
    await wait_for(lambda: p.stats["accepted"] == 6)
    assert w.writes == []  # buffered, not yet written
    await p.stop()
    assert len(w.of(Interval.M1)) == 6  # flushed on stop
    assert p.finished
    assert prov.disconnected
    assert all(t.done() for t in p._tasks)


async def test_stop_without_start_and_double_stop_are_safe() -> None:
    p = make(FakeProvider([]))
    await p.stop()
    await p.stop()
    p.start()
    p.start()  # idempotent
    await p.stop()


async def test_cancelling_run_cleans_up_background_tasks() -> None:
    p = make(FakeProvider([mk("SPY", 0)], hang=True), writer=Writer())
    task = asyncio.create_task(p.run())
    await wait_for(lambda: p.stats["accepted"] == 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert all(t.done() for t in p._tasks)
    assert p._monitor_task is not None and p._monitor_task.done()


# --------------------------------------------------------------------------- history / features


async def test_frame_history_is_capped_to_history_bars() -> None:
    engine = StubEngine()
    cfg = settings(features=FeatureConfig(history_bars=50))
    bars = [b for m in range(200) for b in triple(m)]
    p = make(FakeProvider(bars), engine=engine, cfg=cfg, writer=Writer())
    await run(p)
    assert engine.calls
    assert max(h for _, _, fr in engine.calls for h, _ in fr.values()) <= 50
    hist = p.history("NVDA")
    assert hist is not None and hist.height == 50
    assert hist["timestamp"][-1] == T0 + timedelta(minutes=199)
    assert all(len(b.rows) < 50 for b in p._buf.values())


async def test_features_wait_for_benchmark_bars_and_never_see_the_future() -> None:
    engine = StubEngine()
    # NVDA lags both benchmarks by one minute: SPY/SOXX are already at minute t+1 when NVDA@t
    # arrives, yet the engine must only see rows <= t.
    bars = [
        mk("SOXX", 0),
        mk("SPY", 0),
        mk("SOXX", 1),
        mk("SPY", 1),
        mk("NVDA", 0),
        mk("NVDA", 1),
    ]
    p = make(FakeProvider(bars), engine=engine)
    await run(p)
    assert [(s, a) for s, a, _ in engine.calls] == [
        ("NVDA", T0),
        ("NVDA", T0 + timedelta(minutes=1)),
    ]
    _, _, frames = engine.calls[0]
    assert all(last <= T0 for _, last in frames.values())


async def test_equity_is_evaluated_only_after_benchmarks_of_that_minute_arrive() -> None:
    engine = StubEngine()
    p = make(FakeProvider(), engine=engine)
    await p._process(mk("NVDA", 0))
    assert engine.calls == []  # benchmarks missing entirely
    await p._process(mk("SOXX", 0))
    assert engine.calls == []  # market benchmark still missing
    await p._process(mk("SPY", 0))
    assert [(s, a) for s, a, _ in engine.calls] == [("NVDA", T0)]
    _, _, frames = engine.calls[0]
    assert {k: last for k, (_, last) in frames.items()} == {"NVDA": T0, "SOXX": T0, "SPY": T0}


async def test_missing_benchmark_bar_delays_evaluation_by_at_most_one_minute() -> None:
    engine = StubEngine()
    p = make(FakeProvider(), engine=engine)
    for b in triple(0):
        await p._process(b)
    await p._process(mk("NVDA", 1))
    await p._process(mk("SOXX", 1))  # SPY@1 never arrives
    assert len(engine.calls) == 1
    await p._process(mk("NVDA", 2))  # a later minute is seen -> NVDA@1 is released
    assert [a for _, a, _ in engine.calls] == [T0, T0 + timedelta(minutes=1)]


async def test_benchmarks_are_never_evaluated_and_evaluate_from_skips_warmup() -> None:
    engine = StubEngine()
    bars = [b for m in range(10) for b in triple(m)]
    p = make(
        FakeProvider(bars), engine=engine, writer=Writer(), evaluate_from=T0 + timedelta(minutes=6)
    )
    await run(p)
    assert {s for s, _, _ in engine.calls} == {"NVDA"}
    assert [a for _, a, _ in engine.calls] == [T0 + timedelta(minutes=m) for m in range(6, 10)]
    hist = p.history("NVDA")
    assert hist is not None and hist.height == 10  # warm-up bars are still ingested


async def test_unknown_symbols_and_non_1m_bars_are_ignored() -> None:
    p = make(FakeProvider())
    await p._process(mk("ZZZZ", 0))
    await p._process(mk("SPY", 0).model_copy(update={"interval": Interval.M5}))
    assert p.stats["ignored"] == 2 and p.stats["accepted"] == 0


# --------------------------------------------------------------------------- events


def _emit_at(minute: int) -> Callable[[SymbolFeatures], bool]:
    return lambda f: f.as_of == T0 + timedelta(minutes=minute)


async def test_shock_decision_is_delivered_to_sink_and_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    events: list[EventCreate] = []

    async def sink(e: EventCreate) -> None:
        events.append(e)

    det = StubDetector(level=lambda f: ShockLevel.SHOCK, emit=_emit_at(5))
    p = make(FakeProvider([b for m in range(10) for b in triple(m)]), sink=sink, detector=det)
    with caplog.at_level(logging.INFO, logger="echo.market.pipeline"):
        await run(p)
    assert len(events) == 1
    e = events[0]
    assert e.event_type == "market_shock" and e.source_type.value == "market"
    assert e.id == "evt_mkt_nvda_202503031435_neg" and e.companies == ["NVDA"]
    assert e.is_mock is False and e.metadata["provider"] == "massive"
    (rec,) = records(caplog, "market_shock_detected")
    assert rec.levelno == logging.INFO and rec.symbol == "NVDA"
    assert rec.level == "shock"
    assert p.stats["events_emitted"] == 1


async def test_sink_failure_is_contained_and_retried() -> None:
    attempts: list[str] = []
    delivered: list[str] = []

    async def flaky(e: EventCreate) -> None:
        attempts.append(e.id or "")
        if len(attempts) == 1:
            raise ConnectionError("db down")
        delivered.append(e.id or "")

    det = StubDetector(level=lambda f: ShockLevel.SHOCK, emit=_emit_at(5))
    p = make(FakeProvider([b for m in range(8) for b in triple(m)]), sink=flaky, detector=det)
    await run(p)  # never raises
    assert p.stats["sink_failures"] == 1
    assert delivered == ["evt_mkt_nvda_202503031435_neg"]  # retried at the end of the stream


async def test_permanently_failing_sink_does_not_break_the_loop() -> None:
    async def broken(e: EventCreate) -> None:
        raise RuntimeError("nope")

    det = StubDetector(level=lambda f: ShockLevel.SHOCK, emit=lambda f: True)
    p = make(FakeProvider([b for m in range(6) for b in triple(m)]), sink=broken, detector=det)
    await run(p)
    assert p.stats["accepted"] == 18
    assert p.stats["sink_failures"] >= 1


# --------------------------------------------------------------------------- health logs


def test_health_transitions_are_logged_once_and_never_per_tick(
    caplog: pytest.LogCaptureFixture,
) -> None:
    prov = FakeProvider(state=ProviderState.DISCONNECTED)
    p = make(prov)
    with caplog.at_level(logging.DEBUG, logger="echo.market.pipeline"):
        p._observe_health()
        assert not caplog.records  # first observation: no transition
        prov.state = ProviderState.CONNECTED
        p._observe_health()
        for _ in range(5):
            p._observe_health()  # steady state: silent
        assert [r.operation for r in caplog.records] == ["provider_connected"]  # type: ignore[attr-defined]
        assert caplog.records[0].levelno == logging.INFO

        caplog.clear()
        prov.state = ProviderState.RECONNECTING
        p._observe_health()
        prov.state = ProviderState.CONNECTED
        p._observe_health()
        prov.state = ProviderState.STALE
        p._observe_health()
        prov.state = ProviderState.CONNECTED
        p._observe_health()
        prov.state = ProviderState.DISCONNECTED
        p._observe_health()
        prov.malformed = 3
        p._observe_health()
    ops = [r.operation for r in caplog.records]  # type: ignore[attr-defined]
    assert ops == [
        "provider_reconnecting",
        "provider_connected",
        "subscription_started",  # supervisor re-subscribes after a reconnect
        "provider_stale",
        "provider_connected",
        "provider_disconnected",
        "malformed_message",
    ]
    by_op = {r.operation: r.levelno for r in caplog.records}  # type: ignore[attr-defined]
    assert by_op["provider_reconnecting"] == logging.WARNING
    assert by_op["provider_stale"] == logging.WARNING
    assert by_op["malformed_message"] == logging.WARNING
    assert by_op["provider_disconnected"] == logging.INFO


async def test_subscription_started_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    p = make(FakeProvider([mk("SPY", 0)]), writer=Writer())
    with caplog.at_level(logging.INFO, logger="echo.market.pipeline"):
        await run(p)
    (rec,) = records(caplog, "subscription_started")
    assert rec.provider == "massive" and rec.count == 3


async def test_no_info_log_per_bar(caplog: pytest.LogCaptureFixture) -> None:
    p = make(FakeProvider([b for m in range(30) for b in triple(m)]), writer=Writer())
    with caplog.at_level(logging.INFO, logger="echo.market.pipeline"):
        await run(p)
    assert len(caplog.records) < 10  # a handful of state-change lines, not 90+


# --------------------------------------------------------------------------- mode / facade


@pytest.mark.parametrize(
    ("state", "mode"),
    [
        (ProviderState.CONNECTED, DataMode.LIVE),
        (ProviderState.STALE, DataMode.OFFLINE),
        (ProviderState.RECONNECTING, DataMode.OFFLINE),
        (ProviderState.DEGRADED, DataMode.OFFLINE),
        (ProviderState.DISCONNECTED, DataMode.OFFLINE),
        (ProviderState.UNCONFIGURED, DataMode.OFFLINE),
    ],
)
def test_live_mode_only_when_connected(state: ProviderState, mode: DataMode) -> None:
    assert make(FakeProvider(state=state)).mode == mode


@pytest.mark.parametrize("state", list(ProviderState))
def test_replay_is_never_live_even_if_provider_claims_live(state: ProviderState) -> None:
    prov = FakeProvider(name=ProviderName.REPLAY, state=state, health_mode=DataMode.LIVE)
    assert make(prov).mode == DataMode.REPLAY


async def test_replay_failure_keeps_mode_replay_and_not_finished() -> None:
    bars = [mk("SPY", i, ProviderName.REPLAY) for i in range(10)]
    p = make(ReplayMarketDataProvider(bars, fail_after=4), writer=Writer())
    await run(p)
    assert p.mode == DataMode.REPLAY
    assert p.stats["accepted"] == 4
    assert not p.replay_finished


async def test_replay_finished_true_after_end_false_after_early_stop() -> None:
    bars = [mk("SPY", i, ProviderName.REPLAY) for i in range(10)]
    p = make(ReplayMarketDataProvider(bars), writer=Writer())
    assert not p.replay_finished
    await run(p)
    assert p.replay_finished and p.finished

    slow = ReplayMarketDataProvider(bars, speed=1.0, sleep=lambda s: asyncio.sleep(3600))
    q = make(slow, writer=Writer())
    q.start()
    await wait_for(lambda: q.stats["accepted"] >= 1)
    await q.stop()
    assert q.finished and not q.replay_finished


async def test_facade_values() -> None:
    prov = FakeProvider(
        [mk("NVDA", 0, close=100.0), mk("SOXX", 0), mk("SPY", 0), mk("NVDA", 1, close=110.0)],
        hang=True,
    )
    det = StubDetector(level=lambda f: ShockLevel.SEVERE)
    p = make(prov, detector=det, writer=Writer(), cfg=settings(echo_market_queue_size=77))
    assert p.status().mode == DataMode.LIVE
    assert p.queue_stats() == {"depth": 0, "capacity": 77, "dropped": 0}
    assert p.subscribed_symbols == [] and p.last_observation_at is None
    assert p.state_of("NVDA") == "NO_DATA" and p.state_of("SPY") == "NO_DATA"
    p.start()
    try:
        await wait_for(lambda: p.stats["accepted"] == 4)
        await wait_for(lambda: p.stats["evaluated"] >= 1)
        assert set(p.queue_stats()) == {"depth", "capacity", "dropped"}
        assert p.active_provider == ProviderName.MASSIVE
        assert p.subscribed_symbols == UNIV.symbols()
        assert p.last_observation_at == T0 + timedelta(minutes=1)
        price, ts = p.latest_price("nvda") or (None, None)
        assert price == 110.0 and isinstance(price, float) and ts == T0 + timedelta(minutes=1)
        assert p.latest_price("MSFT") is None
        assert p.change_pct("NVDA") == pytest.approx(10.0)
        assert p.change_pct("MSFT") is None
        assert p.latest_features["NVDA"].symbol == "NVDA"
        assert p.latest_assessments["NVDA"].level == ShockLevel.SEVERE
        assert p.state_of("NVDA") == "SEVERE"
        assert p.state_of("SPY") == "NORMAL"  # benchmark with data
        assert p.state_of("MSFT") == "NO_DATA"  # not in this universe
        assert p.state_of("nope") == "NO_DATA"
        (h,) = p.provider_healths()
        assert h.provider == ProviderName.MASSIVE and h.state == ProviderState.CONNECTED
        st = p.status()
        assert st.mode == DataMode.LIVE and st.queue_capacity == 77 and st.dropped == 0
        assert st.last_observation_at == p.last_observation_at and not st.replay_finished
    finally:
        await p.stop()


@pytest.mark.parametrize(
    ("status", "level", "expected"),
    [
        (FeatureStatus.WARMING_UP, ShockLevel.NONE, "WARMING_UP"),
        (FeatureStatus.UNAVAILABLE, ShockLevel.SEVERE, "WARMING_UP"),
        (FeatureStatus.READY, ShockLevel.NONE, "NORMAL"),
        (FeatureStatus.READY, ShockLevel.WATCH, "WATCH"),
        (FeatureStatus.READY, ShockLevel.SHOCK, "SHOCK"),
        (FeatureStatus.READY, ShockLevel.SEVERE, "SEVERE"),
    ],
)
async def test_state_of_equity(status: FeatureStatus, level: ShockLevel, expected: str) -> None:
    p = make(
        FakeProvider(),
        engine=StubEngine(status),
        detector=StubDetector(level=lambda f: level),
    )
    for b in triple(0):
        await p._process(b)
    assert p.state_of("NVDA") == expected


async def test_state_of_equity_with_price_but_no_features_is_warming_up() -> None:
    p = make(FakeProvider())
    await p._process(mk("NVDA", 0))  # benchmarks missing: not evaluated yet
    assert p.state_of("NVDA") == "WARMING_UP"


async def test_change_pct_resets_on_a_new_session_day() -> None:
    p = make(FakeProvider())
    await p._process(mk("SPY", 0, close=100.0))
    await p._process(mk("SPY", 1, close=101.0))
    assert p.change_pct("SPY") == pytest.approx(1.0)
    nxt = mk("SPY", 24 * 60, close=50.0)  # next day, same clock time
    await p._process(nxt)
    assert p.change_pct("SPY") == pytest.approx(0.0)


# --------------------------------------------------------------------------- replay e2e


async def test_replay_of_shock_scenario_emits_market_shock_near_expected_time() -> None:
    """Real engine + real detector over the deterministic scenario (6 warm-up sessions + shock day).

    The scenario is cut 10 minutes after the expected bar and only the last ~15 minutes are
    evaluated (the feature engine costs ~0.1 s/call); baselines still come from all history.
    """
    sc = build_shock_scenario()
    assert sc.expected_shock_at is not None
    expected = sc.expected_shock_at
    shock_start = expected - timedelta(minutes=4)
    bars = [b for b in sc.bars if b.timestamp <= expected + timedelta(minutes=10)]
    events: list[EventCreate] = []

    async def sink(e: EventCreate) -> None:
        events.append(e)

    w = Writer()
    p = MarketPipeline(
        ReplayMarketDataProvider(bars),
        get_universe(),
        settings(echo_market_provider="replay"),
        None,
        sink,
        bar_writer=w,
        evaluate_from=expected - timedelta(minutes=10),
    )
    await run(p, limit_s=180)

    assert p.replay_finished and p.mode == DataMode.REPLAY
    assert p.stats["errors"] == 0 and p.dropped == 0
    assert p.stats["accepted"] == len(bars)
    shocks = [e for e in events if e.event_type == "market_shock"]
    assert shocks, f"no shock emitted; NVDA features: {p.latest_features.get('NVDA')}"
    assert all(e.companies == ["NVDA"] for e in shocks)  # AMD/SOXX/SPY unaffected
    assert all(e.timestamp >= shock_start for e in shocks)  # no false positive before the move
    first = shocks[0]
    assert abs((first.timestamp - expected).total_seconds()) <= 5 * 60
    assert first.is_mock is True and first.metadata["direction"] == "negative"
    assert first.metadata["level"] in ("shock", "severe") and first.severity >= 0.55
    assert first.metadata["provider"] == "replay"
    assert p.state_of("SPY") == "NORMAL" and p.latest_price("NVDA") is not None
    # batched persistence of the whole replay
    assert sum(len(x) for x in w.writes) == len(bars) + p.stats["aggregated"]
    assert len(w.writes) < len(bars) // 50
