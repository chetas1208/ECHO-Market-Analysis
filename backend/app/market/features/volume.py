"""Volume z-score with a time-of-day baseline and a documented rolling fallback.

Intraday volume is strongly seasonal (U-shaped: huge at the open/close, thin at midday), so a
plain rolling z-score flags every market open as an "anomaly". ``add_volume_z`` therefore
compares each bar with the *same time-of-day bucket on prior sessions*:

* bucket = minutes since local midnight in America/New_York // ``bucket_minutes``
  (wall-clock, so the bucket is stable across DST changes); session date = the ET date.
* method ``"tod"``: when at least ``tod_min_days`` strictly earlier ET sessions have
  observations in this bucket, ``z = (v - mean) / std`` (ddof=1) over ALL prior-session
  observations in that bucket. The current session (including its own earlier bars in the
  bucket) is never part of the baseline.
* method ``"rolling"`` (fallback, cold start): the previous ``rolling_window`` bars
  (current excluded) if at least ``min_periods`` are usable.

Fallback limitation: the rolling baseline ignores seasonality. During warm-up (fewer than
``tod_min_days`` prior sessions, e.g. a fresh deployment or the first days of a symbol) the
opening/closing volume surge is compared with quiet pre-open/midday bars and will look
anomalous, and a genuine spike right after a lull is over-stated. Consumers must treat
``"rolling"`` z-scores as lower quality than ``"tod"`` (the method column exposes which).

Otherwise (insufficient samples) both columns are null. Zero variance -> null z (the method
still names the baseline that was selected). Never emits inf/NaN. Strictly causal: row t only
reads rows earlier than t (rolling) or earlier sessions (tod).
"""

from __future__ import annotations

import math
from bisect import bisect_left
from datetime import date

import numpy as np
import polars as pl

_ET = "America/New_York"


def _z(value: float, baseline: np.ndarray) -> float | None:
    """z of ``value`` against ``baseline`` (ddof=1); None if <2 samples or zero variance."""
    if baseline.size < 2 or float(baseline.max()) == float(baseline.min()):
        return None
    std = float(baseline.std(ddof=1))
    if not math.isfinite(std) or std <= 0.0:
        return None
    z = (value - float(baseline.mean())) / std
    return z if math.isfinite(z) else None


def add_volume_z(
    df: pl.DataFrame,
    out: str,
    *,
    bucket_minutes: int,
    tod_min_days: int,
    rolling_window: int,
    min_periods: int,
) -> pl.DataFrame:
    """Add ``out`` (volume z-score) and ``f"{out}_method"`` ("tod" | "rolling" | null)."""
    if bucket_minutes < 1 or tod_min_days < 1 or rolling_window < 1 or min_periods < 1:
        raise ValueError("bucket_minutes, tod_min_days, rolling_window, min_periods must be >= 1")
    method_col = f"{out}_method"
    base = (
        df.drop([out, method_col], strict=False)
        .unique(subset="timestamp", keep="last", maintain_order=True)
        .sort("timestamp")
    )
    n = base.height
    if n == 0:
        return base.with_columns(
            pl.lit(None, dtype=pl.Float64).alias(out),
            pl.lit(None, dtype=pl.String).alias(method_col),
        )

    et = pl.col("timestamp").dt.convert_time_zone(_ET)
    meta = base.select(
        et.dt.date().alias("d"),
        (
            (et.dt.hour().cast(pl.Int32) * 60 + et.dt.minute().cast(pl.Int32)) // bucket_minutes
        ).alias("b"),
    )
    dates: list[date] = meta["d"].to_list()
    buckets: list[int] = meta["b"].to_list()
    vols = np.array(
        [np.nan if v is None else float(v) for v in base["volume"].to_list()], dtype=np.float64
    )
    vols[~np.isfinite(vols)] = np.nan
    valid = ~np.isnan(vols)

    # Per bucket: ascending (date ordinal, row index) of valid observations + distinct-session
    # count for every prefix, so "prior sessions" is a prefix found by bisect.
    per_bucket: dict[int, tuple[list[int], list[int], list[int]]] = {}
    for i in range(n):
        if not valid[i]:
            continue
        ords, idxs, distinct = per_bucket.setdefault(buckets[i], ([], [], []))
        o = dates[i].toordinal()
        prev = distinct[-1] if distinct else 0
        distinct.append(prev + (0 if ords and ords[-1] == o else 1))
        ords.append(o)
        idxs.append(i)

    z_out: list[float | None] = [None] * n
    m_out: list[str | None] = [None] * n
    for i in range(n):
        if not valid[i]:
            continue
        ords, idxs, distinct = per_bucket[buckets[i]]
        k = bisect_left(ords, dates[i].toordinal())  # observations on strictly earlier dates
        if k > 0 and distinct[k - 1] >= tod_min_days:
            m_out[i] = "tod"
            z_out[i] = _z(float(vols[i]), vols[idxs[:k]])
            continue
        window = vols[max(0, i - rolling_window) : i]
        window = window[~np.isnan(window)]
        if window.size >= min_periods:
            m_out[i] = "rolling"
            z_out[i] = _z(float(vols[i]), window)

    return base.with_columns(
        pl.Series(out, z_out, dtype=pl.Float64),
        pl.Series(method_col, m_out, dtype=pl.String),
    )
