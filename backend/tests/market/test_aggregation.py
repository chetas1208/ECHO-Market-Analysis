from __future__ import annotations

from datetime import UTC, datetime, timedelta

import polars as pl
import pytest

from app.market.aggregation import BarAggregator, aggregate_frame
from app.market.types import Bar, Interval, ProviderName

T0 = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)  # 09:30 ET


def mk(sym: str, i: int, *, base: float = 100.0, vwap: bool = True, **kw) -> Bar:
    c = base + i * 0.1
    args = dict(
        symbol=sym,
        timestamp=T0 + timedelta(minutes=i),
        open=c - 0.05,
        high=c + 0.2 + (i % 3) * 0.01,
        low=c - 0.3 - (i % 4) * 0.01,
        close=c,
        volume=100.0 + i,
        vwap=c - 0.02 if vwap else None,
        trade_count=10 + i,
        source=ProviderName.REPLAY,
    )
    args.update(kw)
    return Bar(**args)


def run(bars: list[Bar], agg: BarAggregator | None = None) -> list[Bar]:
    agg = agg or BarAggregator()
    out: list[Bar] = []
    for b in bars:
        out.extend(agg.add(b))
    return out


def test_full_5m_and_15m_values() -> None:
    bars = [mk("AAA", i) for i in range(15)]
    out = run(bars)
    m5 = [b for b in out if b.interval == Interval.M5]
    m15 = [b for b in out if b.interval == Interval.M15]
    assert [b.timestamp for b in m5] == [T0, T0 + timedelta(minutes=5), T0 + timedelta(minutes=10)]
    assert len(m15) == 1 and m15[0].timestamp == T0
    b = m5[0]
    g = bars[:5]
    assert b.open == g[0].open and b.close == g[-1].close
    assert b.high == max(x.high for x in g) and b.low == min(x.low for x in g)
    assert b.volume == sum(x.volume for x in g) and b.trade_count == sum(10 + i for i in range(5))
    exp = sum(x.vwap * x.volume for x in g) / sum(x.volume for x in g)
    assert b.vwap == pytest.approx(exp)
    assert b.source == ProviderName.REPLAY
    c = m15[0]
    assert c.open == bars[0].open and c.close == bars[14].close
    assert c.volume == sum(x.volume for x in bars) and c.high == max(x.high for x in bars)
    assert c.low == min(x.low for x in bars)


def test_completes_on_last_minute_immediately() -> None:
    agg = BarAggregator((Interval.M5,))
    assert all(agg.add(mk("AAA", i)) == [] for i in range(4))
    (b,) = agg.add(mk("AAA", 4))
    assert b.timestamp == T0 and b.interval == Interval.M5


def test_partial_bucket_emits_on_next_bucket_and_none_vwap() -> None:
    agg = BarAggregator((Interval.M5,))
    assert agg.add(mk("AAA", 0, vwap=False, trade_count=None)) == []
    assert agg.add(mk("AAA", 2, vwap=False, trade_count=None)) == []
    (b,) = agg.add(mk("AAA", 5))  # bar of later bucket completes partial one
    assert b.timestamp == T0 and b.volume == 100.0 + 102.0
    assert b.vwap is None and b.trade_count is None
    assert b.open == mk("AAA", 0).open and b.close == mk("AAA", 2).close


def test_partial_bucket_sums_trade_count_and_flush() -> None:
    agg = BarAggregator((Interval.M5,))
    agg.add(mk("AAA", 0))
    agg.add(mk("AAA", 1))
    (b,) = agg.flush()
    assert b.trade_count == 10 + 11 and b.volume == 201.0
    assert agg.flush() == []


def test_multi_symbol_interleave() -> None:
    a = [mk("AAA", i) for i in range(10)]
    b = [mk("BBB", i, base=50.0) for i in range(10)]
    inter = [x for pair in zip(a, b, strict=True) for x in pair]
    out = run(inter, BarAggregator((Interval.M5,)))
    by = {s: [x for x in out if x.symbol == s] for s in ("AAA", "BBB")}
    assert len(by["AAA"]) == len(by["BBB"]) == 2
    assert by["AAA"][0].close == a[4].close and by["BBB"][0].close == b[4].close
    assert by["BBB"][1].high == max(x.high for x in b[5:])


def test_duplicates_ignored_first_wins() -> None:
    agg = BarAggregator((Interval.M5,))
    first = mk("AAA", 1)
    changed = mk("AAA", 1, close=first.close + 0.05, high=first.high + 1, volume=9999.0)
    run([mk("AAA", 0), first, first, changed], agg)
    assert agg.duplicates_dropped == 2 and agg.late_dropped == 0
    out = run([mk("AAA", i) for i in (2, 3, 4)], agg)
    (b,) = out
    assert b.volume == 100.0 + 101.0 + 102.0 + 103.0 + 104.0
    assert b.high == max(mk("AAA", i).high for i in range(5))


def test_duplicate_after_bucket_closed_is_duplicate_not_late() -> None:
    agg = BarAggregator((Interval.M5,))
    run([mk("AAA", i) for i in range(6)], agg)
    assert agg.add(mk("AAA", 3)) == []
    assert agg.duplicates_dropped == 1 and agg.late_dropped == 0


def test_late_bar_dropped_and_counted() -> None:
    agg = BarAggregator()
    run([mk("AAA", i) for i in (0, 1, 2, 16)], agg)  # 5m and 15m bucket 0 emitted partial
    assert agg.add(mk("AAA", 3)) == []  # new (unseen) minute in older bucket
    assert agg.late_dropped == 1
    # other symbol unaffected
    assert agg.add(mk("BBB", 3)) == []
    assert agg.late_dropped == 1


def test_late_bar_in_closed_bucket_same_bucket() -> None:
    agg = BarAggregator((Interval.M5,))
    run([mk("AAA", i) for i in (0, 1, 2, 4)], agg)  # completes via last minute
    assert agg.add(mk("AAA", 3)) == []
    assert agg.late_dropped == 1


def test_out_of_order_within_current_bucket_uses_timestamp_order() -> None:
    agg = BarAggregator((Interval.M5,))
    run([mk("AAA", 2), mk("AAA", 0), mk("AAA", 1), mk("AAA", 3)], agg)
    (b,) = agg.add(mk("AAA", 4))
    assert b.open == mk("AAA", 0).open and b.close == mk("AAA", 4).close


def test_invalid_interval() -> None:
    with pytest.raises(ValueError):
        BarAggregator((Interval.M1,))


def to_frame(bars: list[Bar]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "timestamp": [b.timestamp for b in bars],
            "open": [b.open for b in bars],
            "high": [b.high for b in bars],
            "low": [b.low for b in bars],
            "close": [b.close for b in bars],
            "volume": [b.volume for b in bars],
            "vwap": [b.vwap for b in bars],
            "trade_count": [b.trade_count for b in bars],
        },
        schema_overrides={"timestamp": pl.Datetime("us", "UTC")},
    )


@pytest.mark.parametrize("interval", [Interval.M5, Interval.M15])
def test_streaming_equals_aggregate_frame(interval: Interval) -> None:
    # 47 bars with gaps (missing minutes) and some bars lacking vwap/trade_count
    idx = [i for i in range(47) if i % 7 != 3]
    bars = [
        mk("AAA", i, vwap=(i % 5 != 0), trade_count=(None if i % 11 == 0 else 10 + i)) for i in idx
    ]
    agg = BarAggregator((interval,))
    stream = run(bars, agg) + agg.flush()
    stream.sort(key=lambda b: b.timestamp)
    batch = aggregate_frame(to_frame(bars), interval)
    assert batch.height == len(stream)
    for row, b in zip(batch.iter_rows(named=True), stream, strict=True):
        assert row["timestamp"] == b.timestamp
        for k in ("open", "high", "low", "close", "volume"):
            assert row[k] == pytest.approx(getattr(b, k))
        assert row["trade_count"] == b.trade_count
        if b.vwap is None:
            assert row["vwap"] is None
        else:
            assert row["vwap"] == pytest.approx(b.vwap)


def test_aggregate_frame_dedupes_first_and_sorts_and_nulls() -> None:
    bars = [mk("AAA", i, vwap=False, trade_count=None) for i in (4, 1, 0)]
    dup = mk("AAA", 1, close=105.0, high=106.0, volume=5000.0, vwap=False, trade_count=None)
    df = to_frame([*bars, dup])
    out = aggregate_frame(df, Interval.M5)
    assert out.height == 1
    r = out.row(0, named=True)
    assert r["timestamp"] == T0 and r["vwap"] is None and r["trade_count"] is None
    assert r["volume"] == 100.0 + 101.0 + 104.0 and r["open"] == mk("AAA", 0).open
    assert r["close"] == mk("AAA", 4).close


def test_aggregate_frame_empty() -> None:
    assert aggregate_frame(to_frame([]), Interval.M5).height == 0
