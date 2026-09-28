"""1m -> 5m/15m aggregation: streaming (BarAggregator) and batch (aggregate_frame).

Buckets align to the UTC clock (minute-of-hour multiples of the interval), which is
correct for NYSE (09:30 ET open sits on a 5m/15m boundary in every UTC offset).
Semantics (identical in both paths): open=first, high=max, low=min, close=last,
volume=sum, vwap=volume-weighted over bars that carry a vwap (None if none),
trade_count=sum (None if none carry it). Duplicate 1m timestamps: FIRST wins.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import polars as pl

from app.market.types import Bar, Interval

_ONE_MIN = timedelta(minutes=1)
_SEEN_PRUNE_AT = 128


def bucket_start(ts: datetime, interval: Interval) -> datetime:
    """Start of the clock-aligned bucket containing ``ts`` (UTC minute arithmetic)."""
    ts = ts.astimezone(UTC).replace(second=0, microsecond=0)
    return ts - timedelta(minutes=ts.minute % interval.minutes)


def _combine(bars: list[Bar], interval: Interval, start: datetime) -> Bar:
    bars = sorted(bars, key=lambda b: b.timestamp)
    vw = [(b.vwap, b.volume) for b in bars if b.vwap is not None]
    vw_vol = sum(v for _, v in vw)
    vwap = sum(p * v for p, v in vw) / vw_vol if vw and vw_vol > 0 else None
    tcs = [b.trade_count for b in bars if b.trade_count is not None]
    return Bar(
        symbol=bars[0].symbol,
        timestamp=start,
        interval=interval,
        open=bars[0].open,
        high=max(b.high for b in bars),
        low=min(b.low for b in bars),
        close=bars[-1].close,
        volume=sum(b.volume for b in bars),
        vwap=vwap,
        trade_count=sum(tcs) if tcs else None,
        source=bars[0].source,
        received_at=bars[-1].received_at,
    )


@dataclass
class _Bucket:
    start: datetime | None = None
    bars: dict[datetime, Bar] = field(default_factory=dict)
    closed: bool = False


@dataclass
class _SymbolState:
    seen: set[datetime] = field(default_factory=set)
    max_ts: datetime | None = None
    buckets: dict[Interval, _Bucket] = field(default_factory=dict)


class BarAggregator:
    """Streaming aggregator of closed 1m bars into clock-aligned higher intervals."""

    def __init__(self, intervals: Sequence[Interval] = (Interval.M5, Interval.M15)) -> None:
        for i in intervals:
            if i.minutes <= 1:
                raise ValueError("aggregation intervals must be > 1m")
        self.intervals: tuple[Interval, ...] = tuple(intervals)
        self._state: dict[str, _SymbolState] = {}
        self.late_dropped = 0
        self.duplicates_dropped = 0

    def add(self, bar: Bar) -> list[Bar]:
        """Feed one closed 1m bar; return any higher-interval bars it completed."""
        st = self._state.setdefault(bar.symbol, _SymbolState())
        ts = bar.timestamp.astimezone(UTC).replace(second=0, microsecond=0)
        if ts in st.seen:  # exact duplicate (first wins, even if values changed)
            self.duplicates_dropped += 1
            return []
        st.seen.add(ts)
        if st.max_ts is None or ts > st.max_ts:
            st.max_ts = ts
        self._prune(st)

        out: list[Bar] = []
        accepted = False
        for interval in self.intervals:
            emitted, ok = self._feed(st, interval, bar, ts)
            out.extend(emitted)
            accepted = accepted or ok
        if not accepted:
            self.late_dropped += 1
        return out

    def _feed(
        self, st: _SymbolState, interval: Interval, bar: Bar, ts: datetime
    ) -> tuple[list[Bar], bool]:
        b = bucket_start(ts, interval)
        bk = st.buckets.setdefault(interval, _Bucket())
        out: list[Bar] = []
        if bk.start is None or b > bk.start:
            if bk.start is not None and not bk.closed and bk.bars:
                out.append(_combine(list(bk.bars.values()), interval, bk.start))
            bk.start, bk.bars, bk.closed = b, {}, False
        elif b < bk.start or bk.closed:
            return out, False  # older than current bucket / bucket already emitted
        bk.bars[ts] = bar
        if ts == b + timedelta(minutes=interval.minutes) - _ONE_MIN:
            out.append(_combine(list(bk.bars.values()), interval, b))
            bk.closed = True
        return out, True

    def _prune(self, st: _SymbolState) -> None:
        if len(st.seen) > _SEEN_PRUNE_AT and st.max_ts is not None:
            span = max(i.minutes for i in self.intervals) * 2
            floor = st.max_ts - timedelta(minutes=span)
            st.seen = {t for t in st.seen if t >= floor}

    def flush(self) -> list[Bar]:
        """Emit all still-open partial buckets (e.g. at end of stream)."""
        out: list[Bar] = []
        for st in self._state.values():
            for interval, bk in st.buckets.items():
                if bk.start is not None and bk.bars and not bk.closed:
                    out.append(_combine(list(bk.bars.values()), interval, bk.start))
                    bk.closed = True
        return sorted(out, key=lambda b: (b.timestamp, b.symbol, b.interval.minutes))


def aggregate_frame(df: pl.DataFrame, interval: Interval) -> pl.DataFrame:
    """Batch equivalent of BarAggregator for one symbol's 1m frame (see module docstring).

    Sorted ascending; duplicate timestamps keep FIRST. Optional ``symbol``/``source``
    columns are carried through. Partial buckets are emitted.
    """
    df = df.sort("timestamp", maintain_order=True).unique(
        subset="timestamp", keep="first", maintain_order=True
    )
    if interval.minutes <= 1 or df.height == 0:
        return df
    cols = df.columns
    has_vwap = "vwap" in cols
    has_tc = "trade_count" in cols
    aggs: list[pl.Expr] = []
    if "symbol" in cols:
        aggs.append(pl.col("symbol").first())
    aggs += [
        pl.col("open").first(),
        pl.col("high").max(),
        pl.col("low").min(),
        pl.col("close").last(),
        pl.col("volume").sum(),
    ]
    if has_vwap:
        num = (pl.col("vwap") * pl.col("volume")).sum()
        den = pl.col("volume").filter(pl.col("vwap").is_not_null()).sum()
        aggs.append(pl.when(den > 0).then(num / den).otherwise(None).cast(pl.Float64).alias("vwap"))
    if has_tc:
        aggs.append(
            pl.when(pl.col("trade_count").count() > 0)
            .then(pl.col("trade_count").sum())
            .otherwise(None)
            .cast(df.schema["trade_count"])
            .alias("trade_count")
        )
    if "source" in cols:
        aggs.append(pl.col("source").first())
    return df.group_by_dynamic(
        "timestamp", every=f"{interval.minutes}m", closed="left", label="left"
    ).agg(aggs)
