"""Tests for app.market.features.volatility (pure, no DB)."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import polars as pl

from app.market.features.volatility import add_realized_vol, add_vol_z

T0 = datetime(2025, 3, 3, 14, 30, tzinfo=UTC)


def frame(closes: list[float], minutes: list[int] | None = None) -> pl.DataFrame:
    mins = minutes if minutes is not None else list(range(len(closes)))
    return pl.DataFrame(
        {
            "timestamp": [T0 + timedelta(minutes=m) for m in mins],
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [100.0] * len(closes),
        },
        schema_overrides={"timestamp": pl.Datetime("us", "UTC")},
    )


def assert_finite_or_null(s: pl.Series) -> None:
    for v in s.to_list():
        assert v is None or math.isfinite(v)


def test_realized_vol_hand_computed() -> None:
    closes = [100.0, 101.0, 100.0, 102.0, 101.0]
    out = add_realized_vol(frame(closes), 3, "rv3")
    r = [math.log(closes[i] / closes[i - 1]) for i in range(1, 5)]
    assert out["ret_1m"][0] is None
    assert math.isclose(out["ret_1m"][1], r[0])
    assert out["rv3"][:3].to_list() == [None, None, None]  # r0 null -> window not full
    assert math.isclose(out["rv3"][3], math.sqrt(sum(x * x for x in r[0:3])))
    assert math.isclose(out["rv3"][4], math.sqrt(sum(x * x for x in r[1:4])))  # incl. current


def test_realized_vol_window_one_is_abs_return() -> None:
    out = add_realized_vol(frame([100.0, 110.0]), 1, "rv1")
    assert out["rv1"][0] is None
    assert math.isclose(out["rv1"][1], abs(math.log(1.1)))


def test_realized_vol_warmup_and_short_frame() -> None:
    out = add_realized_vol(frame([100.0, 101.0, 102.0, 103.0]), 5, "rv")
    assert out["rv"].null_count() == 4
    empty = add_realized_vol(frame([]), 5, "rv")
    assert empty.height == 0 and "rv" in empty.columns


def test_realized_vol_uses_existing_ret_column() -> None:
    df = frame([1.0, 1.0, 1.0]).with_columns(pl.Series("ret_1m", [None, 0.1, -0.2]))
    out = add_realized_vol(df, 2, "rv")
    assert math.isclose(out["rv"][2], math.sqrt(0.1**2 + 0.2**2))


def test_constant_prices_rv_zero_z_null() -> None:
    out = add_realized_vol(frame([50.0] * 30), 5, "rv")
    assert out["rv"][5] == 0.0 and out["rv"][-1] == 0.0
    out = add_vol_z(out, "rv", "z", window=10, min_periods=5)
    assert out["z"].null_count() == out.height


def test_spike_gives_large_finite_z() -> None:
    rets = [0.0005 * (1 + math.sin(i * 1.7)) * (1 if i % 2 else -1) for i in range(60)]
    rets[50] = -0.05  # 5% crash at bar 50
    closes = [100.0]
    for r in rets[1:]:
        closes.append(closes[-1] * math.exp(r))
    out = add_realized_vol(frame(closes), 5, "rv")
    out = add_vol_z(out, "rv", "z", window=30, min_periods=10)
    z = out["z"][50]
    assert z is not None and math.isfinite(z) and z > 10
    assert out["z"][30] is not None and abs(out["z"][30]) < 5
    assert_finite_or_null(out["z"])
    assert_finite_or_null(out["rv"])


def test_vol_z_hand_computed_excludes_current() -> None:
    df = frame([0.0] * 5).with_columns(pl.Series("rv", [1.0, 2.0, 3.0, 4.0, 10.0]))
    out = add_vol_z(df, "rv", "z", window=3, min_periods=3)
    assert out["z"][:3].to_list() == [None, None, None]
    assert math.isclose(out["z"][3], (4.0 - 2.0) / 1.0)  # prev [1,2,3]: mean 2, std 1
    assert math.isclose(out["z"][4], (10.0 - 3.0) / 1.0)  # prev [2,3,4]: mean 3, std 1


def test_vol_z_null_baseline_values_and_insufficient() -> None:
    df = frame([0.0] * 6).with_columns(pl.Series("rv", [None, 1.0, None, 2.0, 3.0, 9.0]))
    out = add_vol_z(df, "rv", "z", window=4, min_periods=3)
    assert out["z"][4] is None  # only 2 valid baseline values
    assert out["z"][5] is not None  # baseline [1,None,2,3] -> 3 valid
    assert math.isclose(out["z"][5], (9.0 - 2.0) / 1.0)


def test_vol_z_constant_nonzero_baseline_is_null() -> None:
    df = frame([0.0] * 8).with_columns(pl.Series("rv", [0.0123] * 7 + [0.5]))
    out = add_vol_z(df, "rv", "z", window=5, min_periods=3)
    assert out["z"][7] is None


def test_gaps_use_available_rows_only() -> None:
    closes = [100.0, 101.0, 103.0, 102.0]
    out = add_realized_vol(frame(closes, [0, 1, 5, 6]), 2, "rv")  # 3-minute hole, no fill
    assert out.height == 4
    r = [math.log(closes[i] / closes[i - 1]) for i in range(1, 4)]
    assert math.isclose(out["ret_1m"][2], r[1])
    assert math.isclose(out["rv"][2], math.sqrt(r[0] ** 2 + r[1] ** 2))


def test_unsorted_and_duplicate_timestamps() -> None:
    a = frame([100.0, 101.0, 102.0, 101.0])
    shuffled = pl.concat([a[3], a[0], a[2], a[1], a[2]])
    dup = shuffled.with_columns(
        pl.when(pl.col("timestamp") == a["timestamp"][2])
        .then(pl.col("close") + 0.0)
        .otherwise(pl.col("close"))
        .alias("close")
    )
    out = add_realized_vol(dup, 2, "rv")
    ref = add_realized_vol(a, 2, "rv")
    assert out.height == 4
    assert out["rv"].to_list() == ref["rv"].to_list()


def test_bad_prices_never_inf_nan() -> None:
    out = add_realized_vol(frame([100.0, 0.0, 100.0, -1.0, 100.0, 101.0]), 1, "rv")
    assert_finite_or_null(out["rv"])
    assert_finite_or_null(out["ret_1m"])
    assert out["rv"][1] is None and out["rv"][2] is None


def test_no_lookahead() -> None:
    base = [100.0 + math.sin(i / 3) for i in range(80)]
    fut = [*base, 130.0, 60.0, 100.0]  # violent future rows appended
    a = add_vol_z(add_realized_vol(frame(base), 5, "rv"), "rv", "z", 20, 8)
    b = add_vol_z(add_realized_vol(frame(fut), 5, "rv"), "rv", "z", 20, 8)
    assert a["rv"].to_list() == b["rv"].head(80).to_list()
    assert a["z"].to_list() == b["z"].head(80).to_list()
