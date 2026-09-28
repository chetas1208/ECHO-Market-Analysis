from __future__ import annotations

import math
import statistics
from datetime import UTC, datetime, timedelta

import polars as pl
import pytest

from app.market.features.zscore import add_rolling_z


def _frame(values: list[float | None]) -> pl.DataFrame:
    t0 = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
    return pl.DataFrame(
        {
            "timestamp": [t0 + timedelta(minutes=i) for i in range(len(values))],
            "x": pl.Series(values, dtype=pl.Float64),
        }
    ).with_columns(pl.col("timestamp").cast(pl.Datetime("us", "UTC")))


def _z(values, window=4, min_periods=3):
    return add_rolling_z(_frame(values), "x", "z", window, min_periods)["z"].to_list()


def test_known_z_hand_computed():
    z = _z([1.0, 2.0, 3.0, 4.0, 10.0], window=4, min_periods=3)
    # row 3: baseline [1,2,3] mean 2 std 1 -> (4-2)/1 = 2
    # row 4: baseline [1,2,3,4] mean 2.5 std sqrt(5/3) -> 7.5/sqrt(5/3)
    assert z[:3] == [None, None, None]
    assert z[3] == pytest.approx(2.0)
    assert z[4] == pytest.approx(7.5 / math.sqrt(5 / 3))


def test_window_slides_and_excludes_current():
    vals = [1.0, 5.0, 2.0, 8.0, 3.0, 9.0, 4.0]
    z = _z(vals, window=3, min_periods=3)
    for t in range(3, len(vals)):
        base = vals[t - 3 : t]
        expected = (vals[t] - statistics.mean(base)) / statistics.stdev(base)
        assert z[t] == pytest.approx(expected)


def test_warmup_nulls_until_min_periods():
    z = _z([1.0, 2.0, 4.0, 3.0, 5.0, 7.0], window=5, min_periods=4)
    assert z[:4] == [None] * 4
    assert z[4] is not None


def test_zero_variance_is_null():
    for c in (5.0, 0.1, 123456.789, 0.0):
        z = _z([c] * 8 + [c + 1.0, c], window=5, min_periods=3)
        assert z[3:8] == [None] * 5  # constant baseline
        assert z[8] is None  # even a jump vs zero-variance baseline is null, not inf
    assert all(v is None or math.isfinite(v) for v in z)


def test_null_values_in_baseline_are_skipped():
    vals = [1.0, None, 2.0, None, 3.0, 4.0, None, 6.0]
    z = _z(vals, window=3, min_periods=3)
    # null rows are null
    assert z[1] is None and z[3] is None and z[6] is None
    # row 5 (4.0): only 3 prior non-null [1,2,3] -> mean 2 std 1 -> 2
    assert z[5] == pytest.approx(2.0)
    # row 7 (6.0): previous 3 non-null are [2,3,4] -> mean 3 std 1 -> 3
    assert z[7] == pytest.approx(3.0)
    # too few non-null samples before row 4 (only [1,2])
    assert z[4] is None


def test_nan_and_inf_treated_as_null():
    z = _z([1.0, 2.0, float("nan"), 3.0, float("inf"), 4.0, 5.0], window=3, min_periods=3)
    assert z[2] is None and z[4] is None
    assert z[5] == pytest.approx(2.0)  # baseline [1,2,3]
    assert all(v is None or math.isfinite(v) for v in z)


def test_extreme_value_large_finite():
    vals = [1.0, 1.1, 0.9, 1.05, 0.95, 1.0, 1e12]
    z = _z(vals, window=6, min_periods=3)
    assert z[-1] is not None and math.isfinite(z[-1]) and z[-1] > 1e6


def test_no_lookahead_mutation_and_append():
    vals = [1.0, 2.5, 2.0, 4.0, 3.0, 5.5, 4.5, 7.0, 6.0, 8.0]
    base = _z(vals, window=5, min_periods=3)
    mutated = [*vals[:6], 1e9, -1e9, None, 50.0]
    assert _z(mutated, window=5, min_periods=3)[:6] == base[:6]
    appended = [*vals, 100.0, -100.0, 1e6]
    assert _z(appended, window=5, min_periods=3)[: len(vals)] == base
    # mutating the current value changes only that row and later ones
    cur = [*vals[:5], 99.0, *vals[6:]]
    assert _z(cur, window=5, min_periods=3)[:5] == base[:5]


def test_window_smaller_than_min_periods_raises():
    with pytest.raises(ValueError):
        add_rolling_z(_frame([1.0, 2.0, 3.0]), "x", "z", window=2, min_periods=3)
    with pytest.raises(ValueError):
        add_rolling_z(_frame([1.0, 2.0, 3.0]), "x", "z", window=0, min_periods=0)


def test_preserves_columns_and_sorts_dedupes():
    df = _frame([1.0, 2.0, 3.0, 4.0])
    shuffled = pl.concat([df[2:], df[:2], df[3:]])  # out of order + duplicate ts
    out = add_rolling_z(shuffled, "x", "z", 3, 3)
    assert out["timestamp"].is_sorted()
    assert out.height == 4
    assert out["z"].to_list()[3] == pytest.approx(2.0)
    assert set(out.columns) == {"timestamp", "x", "z"}
