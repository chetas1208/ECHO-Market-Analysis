"""Massive adapter tests: pure, no network. The SDK client is replaced by a fake."""

from __future__ import annotations

import asyncio
import math
from datetime import UTC, datetime
from typing import Any

import pytest
from massive.websocket.models import EquityAgg, EquityTrade, EventType

from app.market.providers.base import MarketDataProvider
from app.market.providers.massive import (
    MassiveMarketDataProvider,
    ProviderUnconfigured,
    _default_client_factory,
    normalize_massive_agg,
)
from app.market.types import DataMode, Interval, ProviderName, ProviderState

RECV = datetime(2026, 9, 21, 14, 31, 2, tzinfo=UTC)
KEY = "sekrit-key-123"


def wire(**over: Any) -> dict[str, Any]:
    """Representative AM wire message (2021-01-08 22:27:00Z start)."""
    m: dict[str, Any] = {
        "ev": "AM",
        "sym": "NVDA",
        "v": 4110,
        "av": 9470157,
        "op": 0.4372,
        "vw": 0.4488,
        "o": 0.4488,
        "c": 0.4486,
        "h": 0.4489,
        "l": 0.4486,
        "a": 0.4352,
        "z": 685,
        "s": 1610144820000,
        "e": 1610144880000,
    }
    m.update(over)
    return m


# ------------------------------------------------------------------ normalization


def test_normalize_dict() -> None:
    bar = normalize_massive_agg(wire(), RECV)
    assert bar is not None
    assert bar.symbol == "NVDA"
    assert bar.timestamp == datetime(2021, 1, 8, 22, 27, tzinfo=UTC)
    assert bar.timestamp.utcoffset().total_seconds() == 0
    assert bar.interval is Interval.M1
    assert bar.source is ProviderName.MASSIVE
    assert (bar.open, bar.high, bar.low, bar.close) == (0.4488, 0.4489, 0.4486, 0.4486)
    assert bar.volume == 4110
    assert bar.vwap == 0.4488
    assert bar.trade_count is None  # `z` is average trade size, not a count
    assert bar.received_at == RECV


def test_normalize_sdk_model_matches_dict() -> None:
    model = EquityAgg.from_dict(wire())
    assert normalize_massive_agg(model, RECV) == normalize_massive_agg(wire(), RECV)


def test_normalize_sdk_model_with_enum_event_type() -> None:
    model = EquityAgg.from_dict(wire())
    model.event_type = EventType.EquityAggMin
    bar = normalize_massive_agg(model, RECV)
    assert bar is not None and bar.symbol == "NVDA"


def test_symbol_uppercased_and_timestamp_ms_precision() -> None:
    bar = normalize_massive_agg(wire(sym="spy", s=1610144820000 + 12_345), RECV)
    assert bar is not None
    assert bar.symbol == "SPY"
    assert bar.timestamp == datetime(2021, 1, 8, 22, 27, tzinfo=UTC)  # floored to the minute


def test_timestamp_conversion_is_utc_ms() -> None:
    bar = normalize_massive_agg(wire(s=0 + 60_000), RECV)
    assert bar is not None and bar.timestamp == datetime(1970, 1, 1, 0, 1, tzinfo=UTC)
    # 2026-09-21 13:30:00Z = 09:30 ET
    ms = int(datetime(2026, 9, 21, 13, 30, tzinfo=UTC).timestamp() * 1000)
    bar = normalize_massive_agg(wire(s=ms), RECV)
    assert bar is not None and bar.timestamp == datetime(2026, 9, 21, 13, 30, tzinfo=UTC)


def test_optional_fields_missing_ok() -> None:
    msg = {k: v for k, v in wire().items() if k not in {"vw", "av", "op", "a", "z", "e"}}
    bar = normalize_massive_agg(msg, RECV)
    assert bar is not None and bar.vwap is None


def test_zero_volume_allowed_bad_vwap_dropped() -> None:
    bar = normalize_massive_agg(wire(v=0, vw=-1.0), RECV)
    assert bar is not None and bar.volume == 0 and bar.vwap is None


@pytest.mark.parametrize("ev", ["A", "T", "Q", "status", "am", "XA"])
def test_non_am_events_ignored(ev: str) -> None:
    assert normalize_massive_agg(wire(ev=ev), RECV) is None


def test_non_am_sdk_model_ignored() -> None:
    trade = EquityTrade.from_dict({"ev": "T", "sym": "NVDA", "p": 100.0, "s": 5, "t": 1})
    assert normalize_massive_agg(trade, RECV) is None


def _drop(key: str) -> dict[str, Any]:
    m = wire()
    del m[key]
    return m


MALFORMED: list[Any] = [
    None,
    {},
    [],
    "AM",
    b"AM",
    42,
    object(),
    {"ev": "AM"},
    _drop("sym"),
    _drop("o"),
    _drop("h"),
    _drop("l"),
    _drop("c"),
    _drop("v"),
    _drop("s"),
    wire(sym=""),
    wire(sym="   "),
    wire(sym=123),
    wire(o="0.44"),
    wire(o=None),
    wire(c=True),
    wire(o=math.nan),
    wire(h=math.inf),
    wire(l=-1.0),
    wire(o=0.0),
    wire(h=0.1, l=0.5),  # high < low
    wire(h=0.40),  # high below open/close
    wire(v=-5),
    wire(v=math.nan),
    wire(s=None),
    wire(s="1610144820000"),
    wire(s=-1),
    wire(s=0),
    wire(s=10**30),  # overflows datetime
    wire(s=math.nan),
    EquityAgg(),  # all-None SDK model
    EquityAgg(event_type="AM", symbol="X"),
]


@pytest.mark.parametrize("msg", MALFORMED)
def test_malformed_returns_none_never_raises(msg: Any) -> None:
    assert normalize_massive_agg(msg, RECV) is None


def test_naive_received_at_is_malformed_not_raise() -> None:
    assert normalize_massive_agg(wire(), datetime(2026, 9, 21, 14, 31)) is None


# ------------------------------------------------------------------ fake client


class FakeClient:
    """Mimics the SDK surface the adapter uses (connect/subscribe/unsubscribe/close/attrs)."""

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.sub_calls: list[tuple[str, ...]] = []
        self.unsub_calls: list[tuple[str, ...]] = []
        self.websocket: object | None = None
        self.schedule_resub = True
        self.handler: Any = None
        self.close_calls = 0
        self.fail_with: BaseException | None = None
        self.fail_before_auth: BaseException | None = None
        self.batches: list[list[Any]] = []
        self._stop = asyncio.Event()
        self.fail_gate = asyncio.Event()
        self.fail_gate.set()

    async def connect(self, processor: Any) -> None:
        self.handler = processor
        if self.fail_before_auth is not None:
            raise self.fail_before_auth
        self.websocket = object()
        self.schedule_resub = False
        for batch in self.batches:
            await processor(batch)
        if self.fail_with is not None:
            await self.fail_gate.wait()
            raise self.fail_with
        await self._stop.wait()  # SDK returns cleanly on ConnectionClosedOK after close()

    def subscribe(self, *topics: str) -> None:
        self.sub_calls.append(topics)

    def unsubscribe(self, *topics: str) -> None:
        self.unsub_calls.append(topics)

    async def close(self) -> None:
        self.close_calls += 1
        self._stop.set()


class Harness:
    def __init__(self, **client_attrs: Any) -> None:
        self.clients: list[FakeClient] = []
        self.client_attrs = client_attrs

    def factory(self, **kwargs: Any) -> FakeClient:
        c = FakeClient(**kwargs)
        for k, v in self.client_attrs.items():
            setattr(c, k, v)
        self.clients.append(c)
        return c


def make(h: Harness, symbols: list[str] | None = None, **kw: Any) -> MassiveMarketDataProvider:
    return MassiveMarketDataProvider(
        KEY,
        symbols if symbols is not None else ["NVDA", "SPY"],
        client_factory=h.factory,
        clock=lambda: RECV,
        ready_timeout_s=2.0,
        **kw,
    )


async def next_bar(agen: Any) -> Any:
    return await asyncio.wait_for(agen.__anext__(), timeout=2)


# ------------------------------------------------------------------ unconfigured


@pytest.mark.parametrize("key", [None, "", "   "])
async def test_unconfigured(key: str | None) -> None:
    h = Harness()
    p = MassiveMarketDataProvider(key, ["NVDA"], client_factory=h.factory)
    hl = p.health()
    assert hl.state is ProviderState.UNCONFIGURED
    assert hl.configured is False
    assert hl.mode is DataMode.OFFLINE
    assert hl.provider is ProviderName.MASSIVE
    with pytest.raises(ProviderUnconfigured):
        await p.connect()
    with pytest.raises(ProviderUnconfigured):
        await p.stream().__anext__()
    assert h.clients == []  # SDK never constructed
    await p.disconnect()  # idempotent/no-op
    assert p.health().state is ProviderState.UNCONFIGURED


def test_provider_satisfies_protocol() -> None:
    assert isinstance(MassiveMarketDataProvider(None, []), MarketDataProvider)


# ------------------------------------------------------------------ connected behaviour


async def test_connect_passes_key_and_am_subscriptions_and_streams() -> None:
    h = Harness()
    p = make(h, ["nvda", "SPY", "NVDA"])
    assert p.health().state is ProviderState.DISCONNECTED
    await p.connect()
    client = h.clients[0]
    assert client.kwargs["api_key"] == KEY
    assert client.kwargs["subscriptions"] == ["AM.NVDA", "AM.SPY"]
    assert client.kwargs["max_reconnects"] >= 0

    hl = p.health()
    assert hl.state is ProviderState.CONNECTED
    assert hl.mode is DataMode.LIVE
    assert hl.configured is True
    assert hl.subscribed_symbols == ["NVDA", "SPY"]

    agen = p.stream()
    second = wire(sym="SPY", s=1610144880000)
    await client.handler(
        [
            EquityAgg.from_dict(wire()),  # model
            second,  # dict
            wire(ev="T"),  # ignored, not malformed
            wire(o=None),  # malformed
            None,  # malformed
        ]
    )
    b1, b2 = await next_bar(agen), await next_bar(agen)
    assert (b1.symbol, b2.symbol) == ("NVDA", "SPY")
    assert b1.source is ProviderName.MASSIVE and b1.received_at == RECV
    hl = p.health()
    assert hl.messages_received == 5
    assert hl.malformed_messages == 2
    assert hl.last_message_at == RECV
    await p.disconnect()


async def test_handler_never_raises_on_garbage_batch() -> None:
    h = Harness()
    p = make(h)
    await p.connect()
    await h.clients[0].handler("not-a-list")
    await h.clients[0].handler([object(), 5, {"ev": None}])
    assert p.health().malformed_messages == 4
    assert p.queue_depth == 0
    await p.disconnect()


async def test_subscribe_unsubscribe_topic_strings() -> None:
    h = Harness()
    p = make(h, ["NVDA"])
    await p.subscribe(["amd"])  # before connect: recorded only
    await p.connect()
    client = h.clients[0]
    assert client.kwargs["subscriptions"] == ["AM.NVDA", "AM.AMD"]

    await p.subscribe(["tsla", "NVDA"])  # NVDA already subscribed
    assert client.sub_calls == [("AM.TSLA",)]
    await p.unsubscribe(["nvda", "ZZZZ"])  # ZZZZ never subscribed
    assert client.unsub_calls == [("AM.NVDA",)]
    assert p.health().subscribed_symbols == ["AMD", "TSLA"]
    await p.subscribe([])
    await p.unsubscribe([])
    assert len(client.sub_calls) == 1 and len(client.unsub_calls) == 1
    await p.disconnect()


@pytest.mark.parametrize("bad", ["*", "", "N VDA", "A" * 30, "AM,SPY"])
def test_invalid_symbols_rejected(bad: str) -> None:
    with pytest.raises(ValueError):
        MassiveMarketDataProvider(KEY, [bad])


async def test_queue_overflow_drops_oldest_and_counts() -> None:
    h = Harness()
    p = make(h, queue_size=3)
    await p.connect()
    minute = 60_000
    base = 1610144820000
    await h.clients[0].handler(
        [wire(s=base + i * minute, o=1 + i, h=10, l=0.5, c=1) for i in range(5)]
    )
    assert p.dropped == 2
    assert p.queue_depth == 3
    assert p.queue_capacity == 3
    agen = p.stream()
    opens = [(await next_bar(agen)).open for _ in range(3)]
    assert opens == [3.0, 4.0, 5.0]  # oldest two dropped, order preserved
    await p.disconnect()


async def test_disconnect_idempotent_and_ends_stream() -> None:
    h = Harness()
    p = make(h)
    await p.disconnect()  # before connect: no-op
    await p.connect()
    agen = p.stream()
    await h.clients[0].handler([wire()])
    assert (await next_bar(agen)).symbol == "NVDA"
    waiter = asyncio.ensure_future(agen.__anext__())
    await asyncio.sleep(0)
    await p.disconnect()
    await p.disconnect()
    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(waiter, 2)
    assert h.clients[0].close_calls == 1
    hl = p.health()
    assert hl.state is ProviderState.DISCONNECTED and hl.mode is DataMode.OFFLINE


async def test_reconnect_after_disconnect_builds_fresh_client() -> None:
    h = Harness()
    p = make(h)
    await p.connect()
    await p.connect()  # already connected: no-op
    assert len(h.clients) == 1
    await p.disconnect()
    await p.connect()
    assert len(h.clients) == 2
    assert p.health().state is ProviderState.CONNECTED
    agen = p.stream()
    await h.clients[1].handler([wire()])
    assert (await next_bar(agen)).symbol == "NVDA"  # no stale EOF from the first session
    await p.disconnect()


async def test_stream_before_connect_raises_connection_error() -> None:
    p = make(Harness())
    with pytest.raises(ConnectionError):
        await p.stream().__anext__()


async def test_link_failure_drains_bars_then_raises_connection_error() -> None:
    gate = asyncio.Event()  # fake stays "connected" until the gate opens (SDK fails after auth)
    h = Harness(
        fail_with=ConnectionResetError(f"link died {KEY}"), batches=[[wire()]], fail_gate=gate
    )
    p = make(h)
    await p.connect()
    gate.set()
    agen = p.stream()
    assert (await next_bar(agen)).symbol == "NVDA"
    with pytest.raises(ConnectionError) as ei:
        await next_bar(agen)
    assert KEY not in str(ei.value)
    hl = p.health()
    assert hl.state is ProviderState.DISCONNECTED
    assert hl.mode is DataMode.OFFLINE
    assert hl.last_error and KEY not in hl.last_error
    await p.disconnect()


async def test_connect_failure_raises_and_reports() -> None:
    h = Harness(fail_before_auth=RuntimeError(f"auth_failed {KEY}"))
    p = make(h)
    with pytest.raises(ConnectionError):
        await p.connect()
    hl = p.health()
    assert hl.state is ProviderState.DISCONNECTED
    assert hl.last_error and "auth_failed" in hl.last_error and KEY not in hl.last_error
    assert hl.reconnect_attempts == 1


async def test_connect_timeout_when_never_authed() -> None:
    class Hang(FakeClient):
        async def connect(self, processor: Any) -> None:
            self.handler = processor
            await asyncio.sleep(60)

    p = MassiveMarketDataProvider(
        KEY, ["NVDA"], client_factory=lambda **kw: Hang(**kw), ready_timeout_s=0.1
    )
    with pytest.raises(ConnectionError, match="timed out"):
        await p.connect()
    assert p.health().state is ProviderState.DISCONNECTED


async def test_sdk_internal_reconnect_reports_reconnecting_not_live() -> None:
    h = Harness()
    p = make(h)
    await p.connect()
    assert p.health().mode is DataMode.LIVE
    h.clients[0].schedule_resub = True  # SDK sets this after ConnectionClosedError
    hl = p.health()
    assert hl.state is ProviderState.RECONNECTING and hl.mode is DataMode.OFFLINE
    await p.disconnect()


# ------------------------------------------------------------------ real SDK constructor


def test_default_factory_builds_real_client_without_network() -> None:
    client = _default_client_factory(
        api_key=KEY, subscriptions=["AM.NVDA"], max_reconnects=2, feed=None
    )
    assert client.api_key == KEY
    assert client.scheduled_subs == {"AM.NVDA"}
    assert client.max_reconnects == 2
    assert client.url == "wss://socket.massive.com/stocks"
    assert client.websocket is None  # nothing connected
