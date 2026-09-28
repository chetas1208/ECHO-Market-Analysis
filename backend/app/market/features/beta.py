"""Rolling beta of a stock's returns against a benchmark's returns (no lookahead)."""

from __future__ import annotations

import numpy as np
import polars as pl
from numpy.lib.stride_tricks import sliding_window_view

_CHUNK = 1024


def _rolling_beta(x: np.ndarray, y: np.ndarray, window: int, min_periods: int) -> np.ndarray:
    """Beta of x on y using the ``window`` rows strictly before each row (NaN = no value)."""
    n = len(x)
    out = np.full(n, np.nan)
    valid = np.isfinite(x) & np.isfinite(y)
    xs = np.where(valid, x, np.nan)
    ys = np.where(valid, y, np.nan)
    pad = np.full(window, np.nan)
    # Row i sees padded[i : i + window] == original rows [i - window, i - 1].
    xw_all = sliding_window_view(np.concatenate([pad, xs]), window)[:n]
    yw_all = sliding_window_view(np.concatenate([pad, ys]), window)[:n]
    for start in range(0, n, _CHUNK):
        xw = xw_all[start : start + _CHUNK]
        yw = yw_all[start : start + _CHUNK]
        ok = np.isfinite(xw)
        cnt = ok.sum(axis=1)
        safe = np.maximum(cnt, 1)
        xm = np.where(ok, xw, 0.0).sum(axis=1) / safe
        ym = np.where(ok, yw, 0.0).sum(axis=1) / safe
        dx = np.where(ok, xw - xm[:, None], 0.0)
        dy = np.where(ok, yw - ym[:, None], 0.0)
        cov = (dx * dy).sum(axis=1)
        var = (dy * dy).sum(axis=1)
        ymax = np.where(ok, yw, -np.inf).max(axis=1)
        ymin = np.where(ok, yw, np.inf).min(axis=1)
        good = (cnt >= min_periods) & (ymax > ymin) & (var > 0.0)
        with np.errstate(all="ignore"):
            beta = np.where(good, cov / np.where(good, var, 1.0), np.nan)
        out[start : start + _CHUNK] = beta
    out[~np.isfinite(out)] = np.nan
    return out


def add_rolling_beta(
    df: pl.DataFrame,
    stock_ret: str,
    bench_ret: str,
    out: str,
    window: int,
    min_periods: int,
) -> pl.DataFrame:
    """Add ``out`` = cov(stock, bench) / var(bench) over the previous ``window`` rows.

    The current row is excluded (no lookahead). Only rows where both returns are finite
    count as valid pairs; fewer than ``min_periods`` pairs or zero benchmark variance
    gives null. The result is never inf/NaN.
    """
    if min_periods < 1 or window < min_periods:
        raise ValueError(f"require 1 <= min_periods <= window (got {min_periods}, {window})")
    if "timestamp" in df.columns:
        df = df.sort("timestamp").unique(subset="timestamp", keep="last", maintain_order=True)
    x = df.get_column(stock_ret).cast(pl.Float64).fill_null(float("nan")).to_numpy()
    y = df.get_column(bench_ret).cast(pl.Float64).fill_null(float("nan")).to_numpy()
    beta = _rolling_beta(x, y, window, min_periods)
    series = pl.Series(out, beta, dtype=pl.Float64).fill_nan(None)
    return df.with_columns(series)
