"""Realized volatility features (causal, never inf/NaN).

``add_realized_vol``: sqrt(sum(r_1m^2)) over the last ``window_bars`` 1m log returns,
INCLUDING the current bar's return. Null until the window is full of valid returns.

``add_vol_z``: z-score of the realized-vol column against the PREVIOUS ``window`` values
(current row excluded). Uses sample std (ddof=1). Null if fewer than ``min_periods`` valid
baseline values or the baseline has zero variance.
"""

from __future__ import annotations

import numpy as np
import polars as pl
from numpy.lib.stride_tricks import sliding_window_view

RET_1M = "ret_1m"
_REL_ZERO_STD = 1e-12  # std below this fraction of |mean| counts as zero variance


def _prepare(df: pl.DataFrame) -> pl.DataFrame:
    """Sort ascending by timestamp; drop duplicate timestamps keeping last."""
    if "timestamp" not in df.columns:
        return df
    return df.sort("timestamp", maintain_order=True).unique(
        subset="timestamp", keep="last", maintain_order=True
    )


def _to_float_array(s: pl.Series) -> np.ndarray:
    """Series -> float64 array, nulls / NaN / inf -> NaN."""
    arr = s.cast(pl.Float64).fill_null(float("nan")).to_numpy().astype(np.float64, copy=True)
    arr[~np.isfinite(arr)] = np.nan
    return arr


def _series_from(arr: np.ndarray, name: str) -> pl.Series:
    """float array -> Series, NaN/inf -> null."""
    return pl.Series(name, arr, dtype=pl.Float64).fill_nan(None)


def _log_return_1m(close: pl.Series) -> pl.Series:
    c = _to_float_array(close)
    out = np.full(c.shape, np.nan)
    if c.size > 1:
        prev, cur = c[:-1], c[1:]
        ok = np.isfinite(prev) & np.isfinite(cur) & (prev > 0) & (cur > 0)
        with np.errstate(all="ignore"):
            out[1:] = np.where(ok, np.log(np.where(ok, cur, 1.0) / np.where(ok, prev, 1.0)), np.nan)
    return _series_from(out, RET_1M)


def add_realized_vol(df: pl.DataFrame, window_bars: int, out: str) -> pl.DataFrame:
    """Add ``out`` = sqrt(sum of squared 1m log returns over last ``window_bars`` rows)."""
    if window_bars < 1:
        raise ValueError("window_bars must be >= 1")
    df = _prepare(df)
    if RET_1M not in df.columns:
        df = df.with_columns(_log_return_1m(df["close"]))
    n = df.height
    if n == 0:
        return df.with_columns(pl.lit(None, dtype=pl.Float64).alias(out))
    r = _to_float_array(df[RET_1M])
    rv = np.full(n, np.nan)
    if n >= window_bars:
        sq = r * r
        windows = sliding_window_view(sq, window_bars)  # windows[j] = sq[j : j + window_bars]
        with np.errstate(all="ignore"):
            rv[window_bars - 1 :] = np.sqrt(windows.sum(axis=1))  # any NaN -> NaN (null)
    return df.with_columns(_series_from(rv, out))


def add_vol_z(
    df: pl.DataFrame, rv_col: str, out: str, window: int, min_periods: int
) -> pl.DataFrame:
    """Add ``out`` = (rv_t - mean(prev window)) / std(prev window); baseline excludes row t."""
    if window < 1 or min_periods < 1:
        raise ValueError("window and min_periods must be >= 1")
    df = _prepare(df)
    n = df.height
    if n == 0:
        return df.with_columns(pl.lit(None, dtype=pl.Float64).alias(out))
    x = _to_float_array(df[rv_col])
    padded = np.concatenate([np.full(window, np.nan), x])
    base = sliding_window_view(padded, window)[:n]  # base[i] = x[i-window : i] (NaN padded)
    mask = np.isfinite(base)
    count = mask.sum(axis=1)
    safe_cnt = np.maximum(count, 1)
    filled = np.where(mask, base, 0.0)
    mean = filled.sum(axis=1) / safe_cnt
    dev = np.where(mask, base - mean[:, None], 0.0)
    var = (dev * dev).sum(axis=1) / np.maximum(count - 1, 1)
    std = np.sqrt(var)
    valid = (
        (count >= max(min_periods, 2))
        & np.isfinite(x)
        & (std > _REL_ZERO_STD * np.abs(mean))
        & (std > 0.0)
    )
    z = np.full(n, np.nan)
    with np.errstate(all="ignore"):
        z[valid] = (x[valid] - mean[valid]) / std[valid]
    z[~np.isfinite(z)] = np.nan
    return df.with_columns(_series_from(z, out))


__all__ = ["add_realized_vol", "add_vol_z"]
