"""Causal rolling z-score (baseline excludes the current value)."""

from __future__ import annotations

import polars as pl

_IDX = "__zscore_row_idx"
_REL_EPS = 1e-9  # std below this fraction of scale is float noise, i.e. zero variance


def add_rolling_z(
    df: pl.DataFrame, col: str, out: str, window: int, min_periods: int
) -> pl.DataFrame:
    """Add ``out`` = (x_t - mean(base)) / std(base), sample std (ddof=1).

    ``base`` is the previous ``window`` non-null, finite values of ``col`` strictly before
    row t (the current value is never in its own baseline, nothing after t is read).
    Result is null when the value is null/non-finite, fewer than ``min_periods`` baseline
    samples exist, or the baseline std is zero. Never inf/NaN.
    """
    if window < 1 or min_periods < 1:
        raise ValueError("window and min_periods must be >= 1")
    if window < min_periods:
        raise ValueError(f"window ({window}) must be >= min_periods ({min_periods})")

    if "timestamp" in df.columns:
        df = df.sort("timestamp", maintain_order=True).unique(
            subset="timestamp", keep="last", maintain_order=True
        )
    df = df.drop(out, strict=False)

    x = pl.col(col).cast(pl.Float64)
    x = pl.when(x.is_finite()).then(x).otherwise(None)
    base = (
        df.select(x.alias("x"))
        .with_row_index(_IDX)
        .filter(pl.col("x").is_not_null())
        .with_columns(pl.col("x").shift(1).alias("b"))
        .with_columns(
            pl.col("b").rolling_mean(window, min_samples=min_periods).alias("mu"),
            pl.col("b").rolling_std(window, min_samples=min_periods, ddof=1).alias("sd"),
        )
        .with_columns(
            pl.when(pl.col("sd") > _REL_EPS * pl.max_horizontal(1.0, pl.col("mu").abs()))
            .then((pl.col("x") - pl.col("mu")) / pl.col("sd"))
            .otherwise(None)
            .alias(out)
        )
        .select(_IDX, out)
    )
    res = (
        df.with_row_index(_IDX)
        .join(base, on=_IDX, how="left", maintain_order="left")
        .with_columns(pl.when(pl.col(out).is_finite()).then(pl.col(out)).otherwise(None).alias(out))
    )
    return res.drop(_IDX)
