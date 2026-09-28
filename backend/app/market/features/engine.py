"""Feature engine: composes the per-feature modules into a ``SymbolFeatures`` snapshot.

Inputs: ``frames`` = {symbol: 1m OHLCV frame}. Frames are sorted ascending, duplicate
timestamps dropped (keep last), and are NEVER forward filled: a missing bar means the
lookback ("1 bar", "5 bars") spans the previous *available* rows.

Definitions (all log returns, all evaluated at the last stock bar; every baseline for row t
uses rows < t only, the sibling modules enforce this):

* ``ret_1m/5m/15m``  = ln(close_t / close_{t-h}), h = 1/5/15 available rows.
* ``return_z``       = rolling z of the 5-bar log return (window ``baseline_bars``,
  min ``min_baseline_bars``, current value excluded).
* ``volume_z``       = ``add_volume_z`` (time-of-day baseline when ``tod_min_days`` prior
  sessions exist, else rolling fallback); ``volume_z_method`` reports which.
* ``volatility_z``   = ``add_vol_z`` over realized vol (sqrt of summed squared 1m returns over
  ``vol_window_bars``) with window ``baseline_bars`` / min ``min_baseline_bars``.
* ``beta_market/sector`` = rolling beta of 1-bar returns vs the market (SPY) / sector ETF
  (``beta_window_bars``, min ``min_beta_bars``, previous rows only).
* ``*_residual``     = r5 - beta * bench_r5 (5-bar returns; null while beta is null, no
  beta=1 fallback). ``*_residual_z`` = z vs previous ``baseline_bars`` residuals.
* Benchmark returns are computed on the benchmark's own frame, then LEFT-joined on
  timestamp (no fill). A stock whose sector benchmark is the market benchmark reuses SPY.
* If the stock IS the market (or sector) benchmark, or that benchmark frame is missing/empty
  or has no bar at ``as_of``, the dependent beta/residual features are UNAVAILABLE.

Status per feature: READY when the value is non-null; WARMING_UP when the stock frame has
rows but the value is null (too little history, or zero variance in the baseline);
UNAVAILABLE when there is no stock frame or the needed benchmark is missing.
``overall_status``: READY iff return_z, volume_z, volatility_z, market_residual_z and
sector_residual_z are all READY; else UNAVAILABLE if any of them is UNAVAILABLE, else
WARMING_UP. ``as_of`` = timestamp of the last stock bar, ``price`` = its close. An empty
stock frame yields ``as_of`` = epoch (1970-01-01 UTC), price None, everything UNAVAILABLE.

The pipeline caps per-symbol history (``FeatureConfig.history_bars``); the engine computes
on whatever it is given. Note the ``tod`` volume baseline needs ``tod_min_days`` prior
sessions in that history, otherwise it falls back to ``rolling``.
"""

from __future__ import annotations

from datetime import UTC, datetime

import polars as pl

from app.market.features.beta import add_rolling_beta
from app.market.features.residual import add_residual, add_residual_z
from app.market.features.returns import add_log_return
from app.market.features.volatility import add_realized_vol, add_vol_z
from app.market.features.volume import add_volume_z
from app.market.features.zscore import add_rolling_z
from app.market.settings import FeatureConfig
from app.market.types import FeatureStatus, FeatureValue, SymbolFeatures
from app.market.universe import Universe

TS = "timestamp"
_TS_DTYPE = pl.Datetime("us", "UTC")
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_MAX_H = 15  # longest return horizon (bars)

_FLOAT_COLS = (
    "close",
    "ret_1m",
    "ret_5m",
    "ret_15m",
    "return_z",
    "volume_z",
    "rv",
    "volatility_z",
    "beta_market",
    "beta_sector",
    "market_residual",
    "market_residual_z",
    "sector_residual",
    "sector_residual_z",
)
SERIES_SCHEMA: dict[str, pl.DataType | type] = {
    TS: _TS_DTYPE,
    **dict.fromkeys(_FLOAT_COLS, pl.Float64),
    "volume_z_method": pl.String,
    "mkt_bar": pl.Boolean,
    "sec_bar": pl.Boolean,
}


def _prep(df: pl.DataFrame | None) -> pl.DataFrame | None:
    """Normalise a raw frame to (timestamp us/UTC, close, volume); None if unusable/empty."""
    if df is None or df.height == 0 or not {TS, "close"} <= set(df.columns):
        return None
    ts = pl.col(TS)
    if isinstance(df.schema[TS], pl.Datetime) and df.schema[TS].time_zone is None:
        ts = ts.dt.replace_time_zone("UTC")
    ts = ts.dt.convert_time_zone("UTC").cast(_TS_DTYPE)
    vol = (
        pl.col("volume").cast(pl.Float64)
        if "volume" in df.columns
        else pl.lit(None, dtype=pl.Float64)
    )
    out = (
        df.select(ts.alias(TS), pl.col("close").cast(pl.Float64), vol.alias("volume"))
        .drop_nulls(TS)
        .sort(TS, maintain_order=True)
        .unique(subset=[TS], keep="last", maintain_order=True)
    )
    return out if out.height else None


def _null(name: str) -> pl.Expr:
    return pl.lit(None, dtype=pl.Float64).alias(name)


class FeatureEngine:
    def __init__(self, universe: Universe, cfg: FeatureConfig) -> None:
        self.universe = universe
        self.cfg = cfg

    # ---- benchmark helpers -------------------------------------------------------------
    @staticmethod
    def _lookup(frames: dict[str, pl.DataFrame], symbol: str) -> pl.DataFrame | None:
        return frames.get(symbol) if symbol in frames else frames.get(symbol.upper())

    def _bench_returns(
        self,
        frames: dict[str, pl.DataFrame],
        bench: str,
        prefix: str,
        start: datetime | None = None,
    ):
        """Benchmark 1-/5-bar returns as (timestamp, {p}_r1, {p}_r5, {p}_bar) or None.

        ``start`` trims to rows at/after it, keeping ``_MAX_H`` earlier rows for the returns.
        """
        b = _prep(self._lookup(frames, bench))
        if b is None:
            return None
        if start is not None:
            b = b.slice(max(int(b[TS].search_sorted(start)) - _MAX_H, 0))
        b = add_log_return(add_log_return(b, 1, f"{prefix}_r1"), 5, f"{prefix}_r5")
        return b.select(TS, f"{prefix}_r1", f"{prefix}_r5", pl.lit(True).alias(f"{prefix}_bar"))

    def _benchmarks(self, symbol: str) -> tuple[str, str]:
        return self.universe.market_benchmark, self.universe.sector_benchmark_for(symbol)

    # ---- per-row pipeline --------------------------------------------------------------
    def _tail_rows(self) -> int:
        """Rows of context that make the LAST row identical to a full-history computation."""
        c = self.cfg
        return c.baseline_bars + c.beta_window_bars + max(_MAX_H, c.vol_window_bars) + 3

    def _last_volume(self, stock: pl.DataFrame) -> tuple[float | None, str | None]:
        """Exact volume z of the last row from a reduced frame.

        Keeps only what the last row's baselines read: every row in its time-of-day bucket
        (prior sessions) and the previous ``baseline_bars`` rows (rolling fallback).
        """
        cfg = self.cfg
        et = pl.col(TS).dt.convert_time_zone("America/New_York")
        bucket = (et.dt.hour().cast(pl.Int32) * 60 + et.dt.minute().cast(pl.Int32)) // (
            cfg.tod_bucket_minutes
        )
        first_tail = max(stock.height - cfg.baseline_bars - 1, 0)
        keep = (bucket == bucket.last()) | (pl.int_range(pl.len()) >= first_tail)
        sub = stock.filter(keep)
        out = add_volume_z(
            sub,
            "volume_z",
            bucket_minutes=cfg.tod_bucket_minutes,
            tod_min_days=cfg.tod_min_days,
            rolling_window=cfg.baseline_bars,
            min_periods=cfg.min_baseline_bars,
        )
        return out["volume_z"][-1], out["volume_z_method"][-1]

    def _build(
        self, symbol: str, frames: dict[str, pl.DataFrame], *, last_only: bool = False
    ) -> tuple[pl.DataFrame, dict[str, bool]]:
        """Return (per-row features, {"mkt": avail, "sec": avail}) for ``symbol``.

        ``last_only`` computes just enough trailing rows for an exact last row (faster).
        """
        cfg = self.cfg
        avail = {"mkt": False, "sec": False}
        stock = _prep(self._lookup(frames, symbol))
        if stock is None:
            return pl.DataFrame(schema=SERIES_SCHEMA), avail

        start: datetime | None = None
        last_volume: tuple[float | None, str | None] | None = None
        if last_only:
            last_volume = self._last_volume(stock)
            stock = stock.tail(self._tail_rows())
            start = stock[TS][0]

        df = add_log_return(stock, 1, "ret_1m")
        df = add_log_return(df, 5, "ret_5m")
        df = add_log_return(df, 15, "ret_15m")
        df = add_rolling_z(df, "ret_5m", "return_z", cfg.baseline_bars, cfg.min_baseline_bars)
        if last_volume is None:
            df = add_volume_z(
                df,
                "volume_z",
                bucket_minutes=cfg.tod_bucket_minutes,
                tod_min_days=cfg.tod_min_days,
                rolling_window=cfg.baseline_bars,
                min_periods=cfg.min_baseline_bars,
            )
        else:  # only the last row is meaningful in last_only mode
            pad = [None] * (df.height - 1)
            df = df.with_columns(
                pl.Series("volume_z", [*pad, last_volume[0]], dtype=pl.Float64),
                pl.Series("volume_z_method", [*pad, last_volume[1]], dtype=pl.String),
            )
        df = add_realized_vol(df, cfg.vol_window_bars, "rv")
        df = add_vol_z(df, "rv", "volatility_z", cfg.baseline_bars, cfg.min_baseline_bars)

        market, sector = self._benchmarks(symbol)
        cache: dict[str, pl.DataFrame | None] = {}
        for tag, bench, prefix in (("mkt", market, "mkt"), ("sec", sector, "sec")):
            if bench.upper() == symbol.upper():
                bdf = None  # a benchmark is not measured against itself
            else:
                if bench not in cache:
                    cache[bench] = self._bench_returns(frames, bench, "b", start)
                bdf = cache[bench]
            if bdf is None:
                df = df.with_columns(
                    pl.lit(False).alias(f"{prefix}_bar"),
                    *(_null(f"{prefix}_{k}") for k in ("r1", "r5")),
                )
            else:
                avail[tag] = True
                bdf = bdf.rename({"b_r1": f"{prefix}_r1", "b_r5": f"{prefix}_r5"}).rename(
                    {"b_bar": f"{prefix}_bar"}
                )
                df = df.join(bdf, on=TS, how="left", maintain_order="left").with_columns(
                    pl.col(f"{prefix}_bar").fill_null(False)
                )

        for prefix, name in (("mkt", "market"), ("sec", "sector")):
            df = add_rolling_beta(
                df,
                "ret_1m",
                f"{prefix}_r1",
                f"beta_{name}",
                cfg.beta_window_bars,
                cfg.min_beta_bars,
            )
            df = add_residual(df, "ret_5m", f"{prefix}_r5", f"beta_{name}", f"{name}_residual")
            df = add_residual_z(
                df,
                f"{name}_residual",
                f"{name}_residual_z",
                cfg.baseline_bars,
                cfg.min_baseline_bars,
            )
        return df.select(list(SERIES_SCHEMA)), avail

    def compute_series(self, symbol: str, frames: dict[str, pl.DataFrame]) -> pl.DataFrame:
        """All per-row features (columns = ``SERIES_SCHEMA``); row t depends on rows <= t."""
        return self._build(symbol, frames)[0]

    # ---- snapshot ----------------------------------------------------------------------
    def compute(self, symbol: str, frames: dict[str, pl.DataFrame]) -> SymbolFeatures:
        market, sector = self._benchmarks(symbol)
        series, avail = self._build(symbol, frames, last_only=True)
        if series.height == 0:
            return SymbolFeatures(
                symbol=symbol, as_of=_EPOCH, sector_benchmark=sector, market_benchmark=market
            )
        row = series.row(-1, named=True)

        def fv(col: str, *, unavailable: bool = False) -> FeatureValue:
            val = row[col]
            if val is not None:
                return FeatureValue(value=float(val), status=FeatureStatus.READY)
            status = FeatureStatus.UNAVAILABLE if unavailable else FeatureStatus.WARMING_UP
            return FeatureValue(value=None, status=status)

        def bench_fv(col: str, group: str, *, needs_bar: bool) -> FeatureValue:
            gone = not avail[group] or (needs_bar and not row[f"{group}_bar"])
            return fv(col, unavailable=gone)

        m = "mkt"
        s = "sec"
        feats = {
            "return_z": fv("return_z"),
            "volume_z": fv("volume_z"),
            "volatility_z": fv("volatility_z"),
            "market_residual_z": bench_fv("market_residual_z", m, needs_bar=True),
            "sector_residual_z": bench_fv("sector_residual_z", s, needs_bar=True),
        }
        statuses = {f.status for f in feats.values()}
        if statuses == {FeatureStatus.READY}:
            overall = FeatureStatus.READY
        elif FeatureStatus.UNAVAILABLE in statuses:
            overall = FeatureStatus.UNAVAILABLE
        else:
            overall = FeatureStatus.WARMING_UP
        close = row["close"]
        return SymbolFeatures(
            symbol=symbol,
            as_of=row[TS],
            price=float(close) if close is not None else None,
            ret_1m=fv("ret_1m"),
            ret_5m=fv("ret_5m"),
            ret_15m=fv("ret_15m"),
            volume_z_method=row["volume_z_method"],
            beta_market=bench_fv("beta_market", m, needs_bar=False),
            beta_sector=bench_fv("beta_sector", s, needs_bar=False),
            market_residual=bench_fv("market_residual", m, needs_bar=True),
            sector_residual=bench_fv("sector_residual", s, needs_bar=True),
            sector_benchmark=sector,
            market_benchmark=market,
            overall_status=overall,
            **feats,
        )
