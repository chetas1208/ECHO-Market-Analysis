"""Log-return feature (causal: row t reads only rows <= t)."""

from __future__ import annotations

import polars as pl

TS = "timestamp"
CLOSE = "close"


def add_log_return(df: pl.DataFrame, horizon_bars: int, out: str) -> pl.DataFrame:
    """Add ``out`` = ln(close_t / close_{t-h}) over ``h`` available rows.

    Sorts by timestamp and drops duplicate timestamps (keep last). Rows are never
    forward filled: a missing bar simply means the lookback is the previous available
    row. The first ``h`` rows, non-positive/null prices and any non-finite result
    yield null (never inf/NaN).
    """
    if horizon_bars < 1:
        raise ValueError("horizon_bars must be >= 1")
    if df.height == 0:
        return df.with_columns(pl.lit(None, dtype=pl.Float64).alias(out))

    frame = df.sort(TS, maintain_order=True).unique(subset=[TS], keep="last", maintain_order=True)
    price = pl.when(pl.col(CLOSE) > 0).then(pl.col(CLOSE).cast(pl.Float64)).otherwise(None)
    ret = (price / price.shift(horizon_bars)).log()
    ret = pl.when(ret.is_finite()).then(ret).otherwise(None)
    return frame.with_columns(ret.cast(pl.Float64).alias(out))
