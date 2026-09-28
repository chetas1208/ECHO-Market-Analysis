"""Unit tests for add_volume_z (time-of-day baseline + rolling fallback). Pure, no DB."""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import polars as pl

from app.market.features.volume import add_volume_z

ET = ZoneInfo("America/New_York")
KW = {"bucket_minutes": 1, "tod_min_days": 5, "rolling_window": 30, "min_periods": 10}


def _noise(s: int, m: int) -> float:
    return float(((s * 7 + m * 37) % 11) * 10)


def _session_rows(d: date, s: int, minutes: int, open_mult: float = 5.0) -> list[tuple]:
    start = datetime(d.year, d.month, d.day, 9, 30, tzinfo=ET)
    rows = []
    for m in range(minutes):
        ts = (start + timedelta(minutes=m)).astimezone(UTC)
        vol = 1000.0 + _noise(s, m)
        if m == 0:
            vol = 1000.0 * open_mult + s * 13.0 % 7 * 20.0
        rows.append((ts, vol))
    return rows


def _frame(dates: list[date], minutes: int = 60, open_mult: float = 5.0) -> pl.DataFrame:
    rows: list[tuple] = []
    for s, d in enumerate(dates):
        rows += _session_rows(d, s, minutes, open_mult)
    return pl.DataFrame(
        rows, schema={"timestamp": pl.Datetime("us", "UTC"), "volume": pl.Float64}, orient="row"
    )


def _weekdays(start: date, n: int) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _at(df: pl.DataFrame, ts: datetime) -> dict:
    return df.filter(pl.col("timestamp") == ts).row(0, named=True)


def _et_ts(d: date, h: int, m: int) -> datetime:
    return datetime(d.year, d.month, d.day, h, m, tzinfo=ET).astimezone(UTC)


DAYS7 = _weekdays(date(2026, 1, 5), 7)


def test_seasonal_open_not_anomalous_under_tod_but_under_naive_rolling() -> None:
    df = _frame(DAYS7)
    tod = add_volume_z(df, "vz", **KW)  # 6 prior sessions >= tod_min_days=5
    naive = add_volume_z(df, "vz", **{**KW, "tod_min_days": 999})
    open_ts = _et_ts(DAYS7[6], 9, 30)
    r_tod, r_naive = _at(tod, open_ts), _at(naive, open_ts)
    assert r_tod["vz_method"] == "tod"
    assert abs(r_tod["vz"]) < 3.0
    assert r_naive["vz_method"] == "rolling"
    assert r_naive["vz"] > 10.0


def test_true_spike_detected_under_tod() -> None:
    df = _frame(DAYS7)
    spike_ts = _et_ts(DAYS7[6], 10, 0)
    df = df.with_columns(
        pl.when(pl.col("timestamp") == spike_ts)
        .then(8000.0)
        .otherwise(pl.col("volume"))
        .alias("volume")
    )
    r = _at(add_volume_z(df, "vz", **KW), spike_ts)
    assert r["vz_method"] == "tod"
    assert r["vz"] > 20.0


def test_method_selection_by_prior_session_count() -> None:
    df = _frame(DAYS7)
    out = add_volume_z(df, "vz", **{**KW, "tod_min_days": 3})

    def method(day_idx: int) -> str | None:
        return _at(out, _et_ts(DAYS7[day_idx], 10, 0))["vz_method"]

    assert method(0) == "rolling"  # 0 prior sessions
    assert method(1) == "rolling"  # 1 prior
    assert method(2) == "rolling"  # 2 prior
    assert method(3) == "tod"  # 3 prior
    assert method(6) == "tod"


def test_tod_baseline_matches_manual_computation() -> None:
    df = _frame(DAYS7)
    out = add_volume_z(df, "vz", **KW)
    ts = _et_ts(DAYS7[6], 10, 15)
    prior = [1000.0 + _noise(s, 45) for s in range(6)]
    mean = sum(prior) / 6
    std = math.sqrt(sum((x - mean) ** 2 for x in prior) / 5)
    cur = 1000.0 + _noise(6, 45)
    assert math.isclose(_at(out, ts)["vz"], (cur - mean) / std, rel_tol=1e-9)


def test_warmup_nulls_and_rolling_min_periods() -> None:
    df = _frame(DAYS7[:1])
    out = add_volume_z(df, "vz", **KW)
    assert out["vz"][:10].null_count() == 10  # <10 prior bars
    assert out["vz_method"][:10].null_count() == 10
    assert out["vz"][10] is not None and out["vz_method"][10] == "rolling"
    # baseline excludes current: window for row 10 = rows 0..9
    prior = df["volume"][:10].to_list()
    mean = sum(prior) / 10
    std = math.sqrt(sum((x - mean) ** 2 for x in prior) / 9)
    assert math.isclose(out["vz"][10], (df["volume"][10] - mean) / std, rel_tol=1e-9)


def test_zero_variance_is_null_never_inf_nan() -> None:
    df = _frame(DAYS7).with_columns(pl.lit(1234.5).alias("volume"))
    out = add_volume_z(df, "vz", **KW)
    assert out["vz"].null_count() == out.height
    assert out.filter(pl.col("vz_method") == "tod").height > 0  # method still reported
    df2 = add_volume_z(_frame(DAYS7, open_mult=5.0), "vz", **KW)
    assert df2["vz"].is_finite().drop_nulls().all()
    assert df2["vz"].is_nan().sum() == 0


def test_dst_change_day_uses_wall_clock_bucket() -> None:
    # US spring-forward: Sun 2026-03-08. Sessions straddle the change (UTC offset -5 -> -4).
    days = [date(2026, 3, 4), date(2026, 3, 5), date(2026, 3, 6), date(2026, 3, 8)]
    days += [date(2026, 3, 9), date(2026, 3, 10)]
    df = _frame(days, minutes=20)
    out = add_volume_z(df, "vz", **{**KW, "tod_min_days": 4})
    # 09:30 ET is 14:30Z before the change and 13:30Z after it.
    assert _et_ts(days[0], 9, 30).hour == 14 and _et_ts(days[4], 9, 30).hour == 13
    last_open = _at(out, _et_ts(days[5], 9, 30))
    assert last_open["vz_method"] == "tod"  # 5 prior sessions matched across the change
    assert abs(last_open["vz"]) < 3.0  # the 5x opening is normal for the 09:30 bucket
    # first session after the change day (4 prior incl. change day) also aligned
    assert _at(out, _et_ts(days[4], 9, 30))["vz_method"] == "tod"
    # session date is the ET date: late-evening ET (next UTC day) stays in its ET session
    late = datetime(2026, 3, 8, 23, 30, tzinfo=ET).astimezone(UTC)
    assert late.date() == date(2026, 3, 9)


def test_et_session_date_not_utc_date() -> None:
    # 20:00 ET on day D is D+1 in UTC; a naive UTC-date grouping would count it as a new session.
    d1, d2 = date(2026, 1, 5), date(2026, 1, 6)
    rows = []
    for s, d in enumerate([d1, d1, d2]):
        # d1 twice on purpose: same ET date -> one session, not two
        ts = datetime(d.year, d.month, d.day, 20, 0 + s, tzinfo=ET).astimezone(UTC)
        rows.append((ts, 100.0 + s))
    df = pl.DataFrame(
        rows, schema={"timestamp": pl.Datetime("us", "UTC"), "volume": pl.Float64}, orient="row"
    )
    out = add_volume_z(df, "vz", bucket_minutes=60, tod_min_days=2, rolling_window=5, min_periods=2)
    # Only one prior ET session (d1) for the d2 bar -> not "tod" with tod_min_days=2.
    assert out["vz_method"][2] == "rolling"
    # And with tod_min_days=1 the d2 bar has 1 prior session (2 obs) -> tod.
    out1 = add_volume_z(
        df, "vz", bucket_minutes=60, tod_min_days=1, rolling_window=5, min_periods=2
    )
    assert out1["vz_method"][2] == "tod"


def test_no_lookahead_truncation_and_future_mutation() -> None:
    df = _frame(DAYS7)
    full = add_volume_z(df, "vz", **KW)
    m = 6 * 60 + 25
    part = add_volume_z(df.head(m), "vz", **KW)
    assert part["vz"].to_list() == full["vz"].head(m).to_list()
    assert part["vz_method"].to_list() == full["vz_method"].head(m).to_list()
    # mutate rows at/after m wildly -> earlier outputs unchanged
    mutated = df.with_columns(
        pl.when(pl.int_range(pl.len()) >= m).then(1e9).otherwise(pl.col("volume")).alias("volume")
    )
    again = add_volume_z(mutated, "vz", **KW)
    assert again["vz"].head(m).to_list() == full["vz"].head(m).to_list()


def test_current_session_earlier_bars_excluded_from_tod_baseline() -> None:
    kw = {**KW, "bucket_minutes": 5, "tod_min_days": 3}
    df = _frame(DAYS7)
    ts_open, ts_next = _et_ts(DAYS7[6], 9, 30), _et_ts(DAYS7[6], 9, 31)
    base = _at(add_volume_z(df, "vz", **kw), ts_next)
    bumped = df.with_columns(
        pl.when(pl.col("timestamp") == ts_open)
        .then(9e6)
        .otherwise(pl.col("volume"))
        .alias("volume")
    )
    assert _at(add_volume_z(bumped, "vz", **kw), ts_next)["vz"] == base["vz"]
    assert base["vz_method"] == "tod"


def test_duplicates_sorted_null_volume_and_empty() -> None:
    df = _frame(DAYS7[:2], minutes=30)
    shuffled = pl.concat([df.reverse(), df.head(3)])  # unsorted + duplicate timestamps
    out = add_volume_z(shuffled, "vz", **KW)
    assert out.height == df.height
    assert out["timestamp"].is_sorted()
    nulled = df.with_columns(
        pl.when(pl.int_range(pl.len()) == 40).then(None).otherwise(pl.col("volume")).alias("volume")
    )
    o = add_volume_z(nulled, "vz", **KW)
    assert o["vz"][40] is None and o["vz_method"][40] is None
    empty = add_volume_z(df.clear(), "vz", **KW)
    assert empty.height == 0 and {"vz", "vz_method"} <= set(empty.columns)
    assert empty.schema["vz"] == pl.Float64
