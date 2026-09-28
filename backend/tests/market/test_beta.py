"""Tests for app.market.features.beta.add_rolling_beta."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import numpy as np
import polars as pl
import pytest

from app.market.features.beta import add_rolling_beta

T0 = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)


def _frame(stock: list[float | None], bench: list[float | None]) -> pl.DataFrame:
    n = len(stock)
    return pl.DataFrame(
        {
            "timestamp": [T0 + timedelta(minutes=i) for i in range(n)],
            "s": pl.Series(stock, dtype=pl.Float64),
            "b": pl.Series(bench, dtype=pl.Float64),
        }
    ).with_columns(pl.col("timestamp").cast(pl.Datetime("us", "UTC")))


def _beta(df: pl.DataFrame, window: int = 30, min_periods: int = 10) -> pl.Series:
    return add_rolling_beta(df, "s", "b", "beta", window, min_periods)["beta"]


def test_noisy_beta_close_to_true() -> None:
    rng = np.random.default_rng(1)
    bench = rng.normal(0, 0.001, 400)
    stock = 1.5 * bench + rng.normal(0, 0.0001, 400)
    df = _frame(stock.tolist(), bench.tolist())
    beta = _beta(df, window=200, min_periods=50)
    assert beta[-1] == pytest.approx(1.5, abs=0.1)
    assert beta.null_count() == 50


def test_exact_beta_two() -> None:
    bench = [0.001 * ((i * 7) % 11 - 5) for i in range(60)]
    df = _frame([2 * b for b in bench], bench)
    beta = _beta(df).drop_nulls()
    assert len(beta) == 50
    assert all(v == pytest.approx(2.0, abs=1e-9) for v in beta)


def test_warmup_nulls_until_min_periods() -> None:
    bench = [0.001 * ((i * 3) % 7 - 3) for i in range(30)]
    beta = _beta(_frame([1.0 * b for b in bench], bench), window=20, min_periods=10)
    assert beta[:10].null_count() == 10  # rows 0..9 have <10 prior rows
    assert beta[10] is not None


def test_zero_variance_benchmark_is_null() -> None:
    n = 40
    stock = [0.001 * (i % 5) for i in range(n)]
    beta = _beta(_frame(stock, [0.0003] * n))
    assert beta.null_count() == n
    assert beta.is_nan().sum() == 0


def test_all_zero_series_null_never_nan_or_inf() -> None:
    beta = _beta(_frame([0.0] * 40, [0.0] * 40))
    assert beta.null_count() == 40


def test_missing_values_skipped_and_counted() -> None:
    n = 60
    bench: list[float | None] = [0.001 * ((i * 5) % 9 - 4) for i in range(n)]
    stock: list[float | None] = [2 * b for b in bench if b is not None]
    for i in range(0, n, 3):
        stock[i] = None
    bench[1] = None
    beta = _beta(_frame(stock, bench), window=30, min_periods=10)
    tail = beta.tail(20)
    assert tail.null_count() == 0
    assert all(v == pytest.approx(2.0, abs=1e-9) for v in tail)
    # Too many gaps: only 3 valid pairs in window -> null.
    sparse_s: list[float | None] = [None] * n
    sparse_b: list[float | None] = [0.001 * (i % 4) for i in range(n)]
    for i in (5, 6, 7):
        sparse_s[i] = 0.002
    assert _beta(_frame(sparse_s, sparse_b), window=30, min_periods=10).null_count() == n


def test_nan_inputs_treated_as_missing() -> None:
    bench = [0.001 * ((i * 5) % 9 - 4) for i in range(40)]
    stock: list[float | None] = [2 * b for b in bench]
    stock[20] = math.nan
    stock[21] = math.inf
    beta = _beta(_frame(stock, bench))
    assert beta.is_nan().sum() == 0
    assert beta[-1] == pytest.approx(2.0, abs=1e-9)


def test_no_lookahead_future_changes_do_not_alter_earlier() -> None:
    rng = np.random.default_rng(7)
    bench = rng.normal(0, 0.001, 120)
    stock = 1.2 * bench + rng.normal(0, 0.0005, 120)
    base = _beta(_frame(stock.tolist(), bench.tolist()), window=40, min_periods=10)
    s2, b2 = stock.copy(), bench.copy()
    s2[80:] = rng.normal(0, 0.05, 40)
    b2[80:] = rng.normal(0, 0.05, 40)
    changed = _beta(_frame(s2.tolist(), b2.tolist()), window=40, min_periods=10)
    assert base[:81].to_list() == changed[:81].to_list()  # row 80 sees rows < 80 only
    assert base[81] != changed[81]


def test_current_row_excluded() -> None:
    bench = [0.001 * ((i * 3) % 7 - 3) for i in range(30)]
    stock = [2 * b for b in bench]
    stock[25] = 10.0  # outlier at row 25 must not affect beta at row 25
    beta = _beta(_frame(stock, bench), window=20, min_periods=10)
    assert beta[25] == pytest.approx(2.0, abs=1e-9)
    assert beta[26] != pytest.approx(2.0, abs=1e-3)


def test_window_lt_min_periods_raises() -> None:
    df = _frame([0.0] * 5, [0.0] * 5)
    with pytest.raises(ValueError):
        add_rolling_beta(df, "s", "b", "beta", 5, 10)
    with pytest.raises(ValueError):
        add_rolling_beta(df, "s", "b", "beta", 5, 0)


def test_short_and_empty_frames() -> None:
    assert _beta(_frame([0.1, 0.2], [0.1, 0.3])).null_count() == 2
    empty = _frame([], [])
    assert add_rolling_beta(empty, "s", "b", "beta", 5, 2).height == 0


def test_sorts_and_dedupes_timestamps() -> None:
    bench = [0.001 * ((i * 5) % 9 - 4) for i in range(30)]
    df = _frame([2 * b for b in bench], bench)
    shuffled = pl.concat([df.reverse(), df.head(1)])
    res = add_rolling_beta(shuffled, "s", "b", "beta", 20, 10)
    assert res.height == 30
    assert res["timestamp"].is_sorted()
    assert res["beta"][-1] == pytest.approx(2.0, abs=1e-9)
    assert "beta" not in df.columns  # input untouched
