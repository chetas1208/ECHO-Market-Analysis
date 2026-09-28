"""Alpaca adapter tests: pure, no network, fake stream running in a real thread."""

from __future__ import annotations

import asyncio
import queue
import threading
from datetime import UTC, datetime, timedelta, timezone

import pytest
from alpaca.data.models import Bar as AlpacaBar

from app.market.providers.alpaca import (
    AlpacaMarketDataProvider,
    ProviderUnconfigured,
    normalize_alpaca_bar,
)
from app.market.providers.base import MarketDataProvider
from app.market.types import DataMode, Interval, ProviderName, ProviderState

T0 = datetime(2026, 3, 2, 15, 0, tzinfo=UTC)
RX = datetime(2026, 3, 2, 15, 1, 1, tzinfo=UTC)


def _raw(symbol="AAPL", ts=T0, **over):
    d = {
        "t": ts,
        "o": 100.0,
        "h": 101.0,
        "l": 99.5,
        "c": 100.5,
        "v": 1234,
        "n": 17,
        "vw": 100.2,
    }
    d.update(over)
    return AlpacaBar(symbol, d)


def _dict(**over):
    d = {
        "symbol": "aapl",
        "timestamp": T0,
        "open": 100.0,
        "high": 101.0,
        "low": 99.5,
        "close": 100.5,
        "volume": 1234.0,
        "trade_count": 17,
        "vwap": 100.2,
    }
    d.update(over)
    return d


# ---- normalization -------------------------------------------------------------------------
def test_normalize_model():
    b = normalize_alpaca_bar(_raw(), RX)
    assert b is not None
    assert (b.symbol, b.timestamp, b.interval, b.source) == (
        "AAPL",
        T0,
        Interval.M1,
        ProviderName.ALPACA,
    )
    assert (b.open, b.high, b.low, b.close, b.volume) == (100.0, 101.0, 99.5, 100.5, 1234.0)
    assert b.trade_count == 17 and b.vwap == 100.2 and b.received_at == RX


def test_normalize_dict_and_wire_keys():
    b = normalize_alpaca_bar(_dict(), RX)
    assert b is not None and b.symbol == "AAPL" and b.trade_count == 17
    wire = {"S": "MSFT", "t": T0, "o": 1, "h": 2, "l": 1, "c": 2, "v": 5, "n": 3, "vw": 1.5}
    w = normalize_alpaca_bar(wire, RX)
    assert w is not None and w.symbol == "MSFT" and w.close == 2.0


def test_normalize_converts_tz_to_utc_and_optional_fields():
    est = timezone(timedelta(hours=-5))
    b = normalize_alpaca_bar(_dict(timestamp=T0.astimezone(est), vwap=None, trade_count=None), RX)
    assert b is not None and b.timestamp == T0 and b.timestamp.utcoffset() == timedelta(0)
    assert b.vwap is None and b.trade_count is None


@pytest.mark.parametrize(
    "over",
    [
        {"timestamp": datetime(2026, 3, 2, 15, 0)},  # naive
        {"timestamp": None},
        {"timestamp": "garbage"},
        {"symbol": None},
        {"symbol": ""},
        {"open": None},
        {"close": "abc"},
        {"close": float("nan")},
        {"high": float("inf")},
        {"volume": -1},
        {"high": 99.0},  # high < low
        {"open": 0.0},  # non-positive price
        {"volume": True},
    ],
)
def test_normalize_malformed_returns_none(over):
    assert normalize_alpaca_bar(_dict(**over), RX) is None


def test_normalize_garbage_inputs():
    assert normalize_alpaca_bar(None, RX) is None
    assert normalize_alpaca_bar(42, RX) is None
    assert normalize_alpaca_bar({}, RX) is None


# ---- fake stream ---------------------------------------------------------------------------
class FakeStream:
    """Mimics StockDataStream: blocking run() with its own loop, thread-safe stop()."""

    def __init__(self, key, secret, feed):
        self.args = (key, secret, feed)
        self.handler = None
        self.symbols: list[str] = []
        self.unsubscribed: list[str] = []
        self._running = False
        self._inbox: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self.stop_calls = 0
        self.crash: Exception | None = None

    def subscribe_bars(self, handler, *symbols):
        self.handler = handler
        self.symbols.extend(s for s in symbols if s not in self.symbols)

    def unsubscribe_bars(self, *symbols):
        for s in symbols:
            self.symbols.remove(s)
            self.unsubscribed.append(s)

    def push(self, raw):
        self._inbox.put(raw)

    def run(self):
        asyncio.run(self._main())

    async def _main(self):
        if self.crash:
            raise self.crash
        self._running = True
        while not self._stop.is_set():
            try:
                raw = self._inbox.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.005)
                continue
            await self.handler(raw)
        self._running = False

    def stop(self):
        self.stop_calls += 1
        self._stop.set()


def _make(**kw):
    holder: dict = {}

    def factory(k, s, f):
        holder["stream"] = FakeStream(k, s, f)
        return holder["stream"]

    kw.setdefault("symbols", ["AAPL", "MSFT"])
    p = AlpacaMarketDataProvider("key", "sec", stream_factory=factory, **kw)
    return p, holder


async def _until(cond, limit=3.0):
    end = asyncio.get_running_loop().time() + limit
    while not cond():
        assert asyncio.get_running_loop().time() < end, "timed out"
        await asyncio.sleep(0.005)


# ---- unconfigured --------------------------------------------------------------------------
@pytest.mark.parametrize("creds", [(None, None), ("k", None), ("", "s")])
async def test_unconfigured(creds):
    p = AlpacaMarketDataProvider(*creds, symbols=["AAPL"])
    h = p.health()
    assert h.state == ProviderState.UNCONFIGURED and not h.configured
    assert h.mode != DataMode.LIVE
    with pytest.raises(ProviderUnconfigured):
        await p.connect()
    await p.disconnect()  # safe


def test_default_factory_builds_real_stream_without_network():
    from alpaca.data.enums import DataFeed
    from alpaca.data.live.stock import StockDataStream

    from app.market.providers.alpaca import _default_stream_factory

    s = _default_stream_factory("k", "s", "sip")
    assert isinstance(s, StockDataStream) and s._endpoint.endswith(DataFeed.SIP.value)
    assert _default_stream_factory("k", "s", "iex")._endpoint.endswith(DataFeed.IEX.value)


def test_satisfies_protocol():
    p, _ = _make()
    assert isinstance(p, MarketDataProvider) and p.name == ProviderName.ALPACA


# ---- flow ----------------------------------------------------------------------------------
async def test_stream_flow_and_health():
    p, h = _make(feed="SIP")
    assert p.health().state == ProviderState.DISCONNECTED
    await p.connect()
    fs = h["stream"]
    assert fs.args == ("key", "sec", "sip") and fs.symbols == ["AAPL", "MSFT"]
    hl = p.health()
    assert hl.state == ProviderState.CONNECTED and hl.mode == DataMode.LIVE
    assert hl.subscribed_symbols == ["AAPL", "MSFT"]

    fs.push(_raw("AAPL", T0))
    fs.push({"bogus": 1})  # malformed: counted, never emitted
    fs.push(_raw("MSFT", T0 + timedelta(minutes=1)))
    it = p.stream()
    got = [await asyncio.wait_for(anext(it), 3) for _ in range(2)]
    assert [(b.symbol, b.source) for b in got] == [
        ("AAPL", ProviderName.ALPACA),
        ("MSFT", ProviderName.ALPACA),
    ]
    assert all(b.received_at is not None for b in got)
    hl = p.health()
    assert hl.messages_received == 2 and hl.malformed_messages == 1
    assert hl.last_message_at is not None

    await p.disconnect()
    assert p.health().state == ProviderState.DISCONNECTED
    assert p.health().mode != DataMode.LIVE
    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(anext(it), 3)
    assert not any(t.name == "alpaca-stream" and t.is_alive() for t in threading.enumerate())


async def test_stream_drains_buffer_before_ending():
    p, h = _make()
    await p.connect()
    for i in range(3):
        h["stream"].push(_raw(ts=T0 + timedelta(minutes=i)))
    await _until(lambda: p.queue_depth == 3)
    await p.disconnect()
    out = [b async for b in p.stream()]
    assert [b.timestamp for b in out] == [T0 + timedelta(minutes=i) for i in range(3)]


async def test_subscribe_unsubscribe_on_running_stream():
    p, h = _make()
    await p.connect()
    fs = h["stream"]
    await p.subscribe(["nvda", "AAPL"])  # AAPL already subscribed, nvda upper-cased
    assert fs.symbols == ["AAPL", "MSFT", "NVDA"]
    assert p.health().subscribed_symbols == ["AAPL", "MSFT", "NVDA"]
    await p.unsubscribe(["msft", "ZZZ"])  # unknown ignored
    assert fs.unsubscribed == ["MSFT"] and fs.symbols == ["AAPL", "NVDA"]
    assert p.health().subscribed_symbols == ["AAPL", "NVDA"]
    await p.unsubscribe(["MSFT"])
    assert fs.unsubscribed == ["MSFT"]
    await p.disconnect()


async def test_connect_without_symbols_starts_on_first_subscribe():
    p, h = _make(symbols=[])
    await p.connect()
    assert p.health().state == ProviderState.CONNECTING and p.health().mode != DataMode.LIVE
    await p.subscribe(["SPY"])
    assert p.health().state == ProviderState.CONNECTED and h["stream"].symbols == ["SPY"]
    await p.disconnect()


async def test_queue_overflow_drops_oldest_and_counts():
    p, h = _make(queue_size=3)
    await p.connect()
    for i in range(10):
        h["stream"].push(_raw(ts=T0 + timedelta(minutes=i)))
    await _until(lambda: p.health().messages_received == 10)
    await _until(lambda: p.dropped == 7)
    assert p.queue_depth == 3
    await p.disconnect()
    out = [b async for b in p.stream()]
    assert [b.timestamp for b in out] == [T0 + timedelta(minutes=i) for i in (7, 8, 9)]


async def test_idempotent_disconnect():
    p, h = _make()
    await p.disconnect()  # before connect
    await p.connect()
    await p.disconnect()
    await p.disconnect()
    assert h["stream"].stop_calls >= 1
    assert p.health().state == ProviderState.DISCONNECTED


async def test_reconnect_after_disconnect_uses_fresh_stream():
    p, h = _make()
    await p.connect()
    first = h["stream"]
    await p.disconnect()
    await p.connect()
    assert h["stream"] is not first and p.health().state == ProviderState.CONNECTED
    h["stream"].push(_raw())
    assert (await asyncio.wait_for(anext(p.stream()), 3)).symbol == "AAPL"
    await p.disconnect()


async def test_stream_thread_crash_fails_connect_and_stays_non_live():
    def factory(k, s, f):
        fs = FakeStream(k, s, f)
        fs.crash = RuntimeError("auth failed")
        return fs

    p = AlpacaMarketDataProvider("k", "s", symbols=["AAPL"], stream_factory=factory)
    with pytest.raises(ConnectionError, match="auth failed"):
        await p.connect()
    hl = p.health()
    assert hl.mode != DataMode.LIVE and hl.last_error and "auth failed" in hl.last_error


async def test_unexpected_thread_exit_raises_from_stream():
    p, h = _make()
    await p.connect()
    h["stream"].push(_raw())
    await _until(lambda: p.queue_depth == 1)
    # simulate the SDK giving up (e.g. insufficient subscription): run() returns on its own
    h["stream"]._stop.set()
    await _until(lambda: p.health().state == ProviderState.DEGRADED)
    it = p.stream()
    assert (await anext(it)).symbol == "AAPL"  # buffered bar still delivered
    with pytest.raises(ConnectionError):
        await anext(it)
    assert p.health().mode != DataMode.LIVE
    await p.disconnect()
