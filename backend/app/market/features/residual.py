"""Beta-adjusted residual returns and their causal z-scores.

Cold start is explicit: a missing beta (or any missing input) yields a null residual.
There is deliberately NO silent ``beta = 1`` fallback.
"""

from __future__ import annotations

import polars as pl

# Rolling std below this is treated as zero variance (guards float noise on constant series).
_ZERO_STD_EPS = 1e-12


def _clean(col: str) -> pl.Expr:
    """Column as Float64 with NaN/inf mapped to null."""
    x = pl.col(col).cast(pl.Float64)
    return pl.when(x.is_finite()).then(x)


def add_residual(
    df: pl.DataFrame,
    stock_ret_h: str,
    bench_ret_h: str,
    beta_col: str,
    out: str,
) -> pl.DataFrame:
    """Add ``out = stock_ret_h - beta * bench_ret_h`` (null if any input is null/non-finite)."""
    residual = _clean(stock_ret_h) - _clean(beta_col) * _clean(bench_ret_h)
    return df.with_columns(pl.when(residual.is_finite()).then(residual).alias(out))


def add_residual_z(
    df: pl.DataFrame,
    resid_col: str,
    out: str,
    window: int,
    min_periods: int,
) -> pl.DataFrame:
    """Add ``out`` = z of the residual vs the previous ``window`` residuals (current excluded).

    Null when fewer than ``min_periods`` (>= 2) prior non-null residuals exist, when the
    baseline std is zero, or when the current residual is null. Never inf/NaN.
    """
    if window < 2:
        raise ValueError("window must be >= 2")
    periods = min(max(min_periods, 2), window)
    x = _clean(resid_col)
    prior = x.shift(1)
    mean = prior.rolling_mean(window_size=window, min_samples=periods)
    std = prior.rolling_std(window_size=window, min_samples=periods)
    z = (x - mean) / std
    valid = std.is_not_null() & (std > _ZERO_STD_EPS) & z.is_finite()
    return df.with_columns(pl.when(valid).then(z).alias(out))
