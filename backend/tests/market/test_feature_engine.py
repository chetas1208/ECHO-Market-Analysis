"""FeatureEngine tests: synthetic frames only (no fixtures.py, no DB, no network)."""

from __future__ import annotations

import math
import time
from datetime import UTC, date, datetime, timedelta

import numpy as np
import polars as pl
import pytest
from polars.testing import assert_frame_equal

from app.market.features.engine import SERIES_SCHEMA, FeatureEngine
from app.market.settings import FeatureConfig
from app.market.types import FeatureStatus, FeatureValue, SymbolFeatures
from app.market.universe import Universe, UniverseEntry

READY = FeatureStatus.READY
WARM = FeatureStatus.WARMING_UP
NA = FeatureStatus.UNAVAILABLE

SESSION_BARS = 390
FIRST_DAY = date(2026, 6, 1)  # Monday, EDT: 09:30 ET == 13:30 UTC

CFG = FeatureConfig(
    baseline_bars=60,
    min_baseline_bars=20,
    beta_window_bars=60,
    min_beta_bars=20,
    vol_window_bars=5,
    tod_bucket_minutes=5,
    tod_min_days=3,
    history_bars=5000,
)


def _universe(soxx_self: bool = False) -> Universe:
    return Universe(
        [
            UniverseEntry(symbol="SPY", group="index", role="benchmark"),
            UniverseEntry(
                symbol="SOXX",
                group="semis",
                role="benchmark",
                sector_benchmark="SOXX" if soxx_self else None,
            ),
            UniverseEntry(symbol="NVDA", group="semis", role="equity", sector_benchmark="SOXX"),
            UniverseEntry(symbol="AAPL", group="tech", role="equity"),  # sector -> SPY
        ],
        market_benchmark="SPY",
    )


def _timestamps(sessions: int) -> list[datetime]:
    out: list[datetime] = []
    day = FIRST_DAY
    while len(out) < sessions * SESSION_BARS:
        if day.weekday() < 5:
            start = datetime(day.year, day.month, day.day, 13, 30, tzinfo=UTC)
            out.extend(start + timedelta(minutes=i) for i in range(SESSION_BARS))
        day += timedelta(days=1)
    return out


def _frame(
    ts: list[datetime],
    rets: np.ndarray,
    *,
    seed: int,
    start: float = 100.0,
    vol_scale: float = 1000.0,
) -> pl.DataFrame:
    rng = np.random.default_rng(seed)
    close = start * np.exp(np.cumsum(rets))
    minute = np.array([(t.hour * 60 + t.minute) for t in ts])
    seasonal = 1.0 + 2.0 * np.exp(-(((minute - 13 * 60 - 30) / 20.0) ** 2))  # open surge
    volume = vol_scale * seasonal * rng.lognormal(0.0, 0.2, len(ts))
    return pl.DataFrame(
        {
            "timestamp": pl.Series("timestamp", ts, dtype=pl.Datetime("us", "UTC")),
            "open": close,
            "high": close * 1.0005,
            "low": close * 0.9995,
            "close": close,
            "volume": volume,
        }
    )


def _market(sessions: int = 5, seed: int = 1) -> dict[str, pl.DataFrame]:
    """SPY, SOXX (beta 1.2 to SPY + noise) and NVDA (beta 1.5 to SOXX + noise)."""
    ts = _timestamps(sessions)
    n = len(ts)
    rng = np.random.default_rng(seed)
    spy = rng.normal(0.0, 0.0004, n)
    soxx = 1.2 * spy + rng.normal(0.0, 0.0003, n)
    nvda = 1.5 * soxx + rng.normal(0.0, 0.0005, n)
    aapl = 1.1 * spy + rng.normal(0.0, 0.0004, n)
    return {
        "SPY": _frame(ts, spy, seed=seed + 10),
        "SOXX": _frame(ts, soxx, seed=seed + 11),
        "NVDA": _frame(ts, nvda, seed=seed + 12),
        "AAPL": _frame(ts, aapl, seed=seed + 13),
    }


def _engine(soxx_self: bool = False) -> FeatureEngine:
    return FeatureEngine(_universe(soxx_self), CFG)


def _finite_or_none(f: SymbolFeatures) -> None:
    for name in SymbolFeatures.model_fields:
        v = getattr(f, name)
        if isinstance(v, FeatureValue) and v.value is not None:
            assert math.isfinite(v.value), name


# ---- happy path ---------------------------------------------------------------------------
def test_full_history_ready_and_definitions() -> None:
    frames = _market()
    f = _engine().compute("NVDA", frames)
    nvda = frames["NVDA"]
    assert f.overall_status == READY
    assert f.as_of == nvda["timestamp"][-1]
    assert f.price == pytest.approx(nvda["close"][-1])
    assert f.market_benchmark == "SPY"
    assert f.sector_benchmark == "SOXX"
    c = nvda["close"].to_numpy()
    assert f.ret_1m.value == pytest.approx(math.log(c[-1] / c[-2]))
    assert f.ret_5m.value == pytest.approx(math.log(c[-1] / c[-6]))
    assert f.ret_15m.value == pytest.approx(math.log(c[-1] / c[-16]))
    assert f.volume_z_method == "tod"
    for name in (
        "return_z",
        "volume_z",
        "volatility_z",
        "beta_market",
        "beta_sector",
        "market_residual",
        "market_residual_z",
        "sector_residual",
        "sector_residual_z",
    ):
        assert getattr(f, name).status == READY, name
    # sector ETF explains more of NVDA than SPY does -> smaller sector residual vol
    assert f.beta_sector.value == pytest.approx(1.5, abs=0.4)
    _finite_or_none(f)


def test_series_last_row_matches_snapshot_and_schema() -> None:
    frames = _market(3)
    eng = _engine()
    series = eng.compute_series("NVDA", frames)
    assert list(series.columns) == list(SERIES_SCHEMA)
    assert series.height == frames["NVDA"].height
    f = eng.compute("NVDA", frames)
    last = series.row(-1, named=True)
    assert f.return_z.value == pytest.approx(last["return_z"])
    assert f.sector_residual_z.value == pytest.approx(last["sector_residual_z"])
    assert f.volume_z_method == last["volume_z_method"]


# ---- no lookahead ---------------------------------------------------------------------------
def test_no_lookahead_truncated_equals_full_pipeline_rows() -> None:
    frames = _market(4)
    eng = _engine()
    full = eng.compute_series("NVDA", frames)
    n = full.height
    for cut in (30, 100, 391, 600, 1000, n - 1):
        trunc = {k: v.head(cut) for k, v in frames.items()}
        part = eng.compute_series("NVDA", trunc)
        assert part.height == cut
        assert_frame_equal(part, full.head(cut), check_exact=False, rel_tol=1e-7, abs_tol=1e-9)
        snap = eng.compute("NVDA", trunc)
        row = full.row(cut - 1, named=True)
        assert snap.as_of == row["timestamp"]
        for name, col in (
            ("ret_5m", "ret_5m"),
            ("return_z", "return_z"),
            ("volume_z", "volume_z"),
            ("volatility_z", "volatility_z"),
            ("beta_market", "beta_market"),
            ("market_residual_z", "market_residual_z"),
            ("sector_residual_z", "sector_residual_z"),
        ):
            got = getattr(snap, name).value
            if row[col] is None:
                assert got is None, (cut, name)
            else:
                assert got == pytest.approx(row[col], rel=1e-7, abs=1e-9), (cut, name)


def test_no_lookahead_future_perturbation_does_not_change_past() -> None:
    frames = _market(3)
    eng = _engine()
    cut = 700
    base = eng.compute_series("NVDA", frames).head(cut)
    rng = np.random.default_rng(5)
    mutated = {}
    for k, v in frames.items():
        junk = pl.Series("close", np.abs(rng.normal(500, 200, v.height - cut)) + 1.0)
        vol = pl.Series("volume", rng.uniform(1e6, 1e9, v.height - cut))
        mutated[k] = pl.concat(
            [
                v.head(cut),
                v.tail(v.height - cut).with_columns(junk.alias("close"), vol.alias("volume")),
            ]
        )
    after = eng.compute_series("NVDA", mutated).head(cut)
    assert_frame_equal(base, after, check_exact=False, rel_tol=1e-9, abs_tol=1e-12)


# ---- warm-up / availability -----------------------------------------------------------------
def test_warmup_statuses_short_frame() -> None:
    frames = {k: v.head(10) for k, v in _market().items()}
    f = _engine().compute("NVDA", frames)
    assert f.ret_1m.status == READY
    assert f.ret_5m.status == READY
    assert f.ret_15m.status == WARM  # only 10 rows
    for name in ("return_z", "volume_z", "volatility_z", "beta_market", "market_residual_z"):
        assert getattr(f, name).status == WARM, name
        assert getattr(f, name).value is None
    assert f.overall_status == WARM
    assert f.volume_z_method is None


def test_warmup_boundary_min_baseline() -> None:
    frames = _market()
    eng = _engine()
    series = eng.compute_series("NVDA", frames)
    first_z = series.with_row_index().filter(pl.col("return_z").is_not_null())["index"][0]
    # ret_5m is first valid at row 5; needs min_baseline_bars(20) prior ret_5m values
    assert first_z == 5 + CFG.min_baseline_bars
    snap_before = eng.compute("NVDA", {k: v.head(first_z) for k, v in frames.items()})
    snap_at = eng.compute("NVDA", {k: v.head(first_z + 1) for k, v in frames.items()})
    assert snap_before.return_z.status == WARM
    assert snap_at.return_z.status == READY


def test_single_row_and_two_rows_do_not_raise() -> None:
    frames = _market()
    for n in (1, 2, 3):
        f = _engine().compute("NVDA", {k: v.head(n) for k, v in frames.items()})
        assert f.overall_status == WARM
        assert f.price is not None


def test_empty_and_missing_frames_unavailable() -> None:
    eng = _engine()
    empty = pl.DataFrame()
    for frames in (
        {},
        {"NVDA": empty, "SPY": empty, "SOXX": empty},
        {"NVDA": _market()["NVDA"].clear()},
    ):
        f = eng.compute("NVDA", frames)
        assert f.overall_status == NA
        assert f.price is None
        assert f.as_of.tzinfo is not None
        assert f.return_z.status == NA
        assert f.ret_1m.status == NA
        assert eng.compute_series("NVDA", frames).height == 0


def test_missing_sector_benchmark_marks_sector_unavailable() -> None:
    frames = _market()
    del frames["SOXX"]
    f = _engine().compute("NVDA", frames)
    assert f.market_residual_z.status == READY
    for name in ("beta_sector", "sector_residual", "sector_residual_z"):
        assert getattr(f, name).status == NA
        assert getattr(f, name).value is None
    assert f.return_z.status == READY
    assert f.overall_status == NA


def test_missing_market_benchmark_marks_market_unavailable() -> None:
    frames = _market()
    frames["SPY"] = frames["SPY"].clear()
    f = _engine().compute("NVDA", frames)
    for name in ("beta_market", "market_residual", "market_residual_z"):
        assert getattr(f, name).status == NA
    assert f.sector_residual_z.status == READY
    assert f.overall_status == NA


def test_benchmark_bar_missing_at_as_of_marks_residual_unavailable() -> None:
    frames = _market()
    frames["SPY"] = frames["SPY"].head(frames["SPY"].height - 1)
    f = _engine().compute("NVDA", frames)
    assert f.market_residual.status == NA and f.market_residual.value is None
    assert f.market_residual_z.status == NA
    assert f.beta_market.status == READY  # beta uses previous rows only
    assert f.sector_residual_z.status == READY


def test_sector_benchmark_spy_reuses_market() -> None:
    frames = _market()
    f = _engine().compute("AAPL", frames)
    assert f.sector_benchmark == "SPY"
    assert f.overall_status == READY
    assert f.sector_residual.value == pytest.approx(f.market_residual.value)
    assert f.beta_sector.value == pytest.approx(f.beta_market.value)
    assert f.sector_residual_z.value == pytest.approx(f.market_residual_z.value)


def test_benchmark_symbol_itself_is_unavailable() -> None:
    frames = _market()
    f = _engine().compute("SPY", frames)  # SPY is market AND default sector benchmark
    for name in (
        "beta_market",
        "market_residual",
        "market_residual_z",
        "beta_sector",
        "sector_residual",
        "sector_residual_z",
    ):
        assert getattr(f, name).status == NA, name
    assert f.return_z.status == READY and f.volume_z.status == READY
    assert f.overall_status == NA

    g = _engine(soxx_self=True).compute("SOXX", frames)  # SOXX vs SPY ok, vs itself not
    assert g.market_residual_z.status == READY
    assert g.sector_residual_z.status == NA
    assert g.sector_residual.value is None


# ---- data quality ---------------------------------------------------------------------------
def test_gap_missing_bars_no_forward_fill() -> None:
    frames = _market()
    nv = frames["NVDA"]
    drop = [1500, 1501, 1502]
    gapped = nv.with_row_index("i").filter(~pl.col("i").is_in(drop)).drop("i")
    frames2 = {**frames, "NVDA": gapped}
    eng = _engine()
    series = eng.compute_series("NVDA", frames2)
    assert series.height == nv.height - 3  # rows never invented
    assert series["timestamp"].n_unique() == series.height
    row = series.filter(pl.col("timestamp") == nv["timestamp"][1503]).row(0, named=True)
    c = nv["close"].to_numpy()
    assert row["ret_1m"] == pytest.approx(math.log(c[1503] / c[1499]))  # previous *available*
    assert eng.compute("NVDA", frames2).overall_status == READY
    # benchmark rows with no stock bar are simply not joined
    assert series.filter(pl.col("timestamp") == nv["timestamp"][1501]).height == 0


def test_stock_missing_last_minute_still_uses_last_available_bar() -> None:
    frames = _market()
    frames["NVDA"] = frames["NVDA"].head(frames["NVDA"].height - 1)
    f = _engine().compute("NVDA", frames)
    assert f.as_of == frames["NVDA"]["timestamp"][-1]
    assert f.overall_status == READY


def test_duplicate_timestamps_keep_last_and_unsorted_input() -> None:
    frames = _market(3)
    nv = frames["NVDA"]
    dup = nv.tail(5).with_columns(pl.col("close") * 1.5)  # stale duplicates arrive first
    messy = pl.concat([dup, nv]).sample(fraction=1.0, shuffle=True, seed=3)
    eng = _engine()
    clean = eng.compute_series("NVDA", frames)
    got = eng.compute_series("NVDA", {**frames, "NVDA": messy})
    # shuffled: the "keep last" winner is undefined for dupes, so compare after removing them
    dedup = pl.concat([nv, dup]).unique(subset="timestamp", keep="first", maintain_order=True)
    assert got.height == clean.height == dedup.height
    ordered = pl.concat([nv, dup]).sort("timestamp", maintain_order=True)
    ordered_series = eng.compute_series("NVDA", {**frames, "NVDA": ordered})
    assert ordered_series.height == clean.height
    assert ordered_series["timestamp"].is_sorted()
    # keep-last semantics on ordered input: last dup close wins
    assert ordered_series["close"][-1] == pytest.approx(dup["close"][-1])


def test_zero_variance_returns_none_never_nan() -> None:
    frames = _market()
    ts = frames["NVDA"]["timestamp"].to_list()
    flat = pl.DataFrame(
        {
            "timestamp": pl.Series("timestamp", ts, dtype=pl.Datetime("us", "UTC")),
            "open": 50.0,
            "high": 50.0,
            "low": 50.0,
            "close": 50.0,
            "volume": 1000.0,
        }
    )
    f = _engine().compute("NVDA", {**frames, "NVDA": flat})
    assert f.ret_5m.value == 0.0
    for name in ("return_z", "volume_z", "volatility_z", "market_residual_z", "sector_residual_z"):
        assert getattr(f, name).value is None, name
        assert getattr(f, name).status != READY
    assert f.overall_status != READY
    _finite_or_none(f)

    flat_bench = {**frames, "SPY": flat}  # zero benchmark variance -> beta null
    g = _engine().compute("NVDA", flat_bench)
    assert g.beta_market.value is None
    assert g.market_residual_z.value is None
    _finite_or_none(g)


def test_extreme_values_stay_finite() -> None:
    frames = _market()
    nv = frames["NVDA"]
    n = nv.height
    crash = nv.with_columns(
        pl.when(pl.int_range(n) >= n - 1)
        .then(pl.col("close") * 1e-3)
        .otherwise(pl.col("close"))
        .alias("close"),
        pl.when(pl.int_range(n) >= n - 1).then(1e15).otherwise(pl.col("volume")).alias("volume"),
    )
    f = _engine().compute("NVDA", {**frames, "NVDA": crash})
    c = nv["close"].to_numpy()
    assert f.ret_1m.value == pytest.approx(math.log(1e-3 * c[-1] / c[-2]))
    assert f.return_z.value is not None and f.return_z.value < -10
    assert f.volume_z.value is not None and f.volume_z.value > 10
    assert f.overall_status == READY
    _finite_or_none(f)

    tiny = nv.with_columns(pl.col("close") * 1e-9, pl.col("volume") * 0.0)
    g = _engine().compute("NVDA", {**frames, "NVDA": tiny})
    _finite_or_none(g)

    bad = nv.with_columns(
        pl.when(pl.int_range(n) == n - 1).then(0.0).otherwise(pl.col("close")).alias("close")
    )
    h = _engine().compute("NVDA", {**frames, "NVDA": bad})  # non-positive price -> null returns
    assert h.ret_1m.value is None and h.ret_1m.status == WARM
    _finite_or_none(h)


def test_naive_timestamps_and_missing_volume_column_do_not_raise() -> None:
    frames = _market(2)
    nv = frames["NVDA"].with_columns(pl.col("timestamp").dt.replace_time_zone(None)).drop("volume")
    f = _engine().compute("NVDA", {**frames, "NVDA": nv})
    assert f.volume_z.status == WARM
    assert f.return_z.status == READY
    assert f.as_of.tzinfo is not None


# ---- performance ----------------------------------------------------------------------------
def test_compute_performance_seven_sessions_three_symbols() -> None:
    frames = _market(7)
    eng = FeatureEngine(_universe(), FeatureConfig())  # production defaults
    frames3 = {k: frames[k] for k in ("SPY", "SOXX", "NVDA")}
    eng.compute("NVDA", frames3)  # warm-up (imports / JIT-free but caches)
    best = min(_timed(eng, frames3) for _ in range(5))
    assert best < 0.300, f"compute took {best * 1000:.0f} ms"


def _timed(eng: FeatureEngine, frames: dict[str, pl.DataFrame]) -> float:
    t0 = time.perf_counter()
    eng.compute("NVDA", frames)
    return time.perf_counter() - t0


def test_tail_optimised_snapshot_equals_full_history_defaults() -> None:
    frames = _market(7)
    eng = FeatureEngine(_universe(), FeatureConfig())
    for sym in ("NVDA", "AAPL"):
        snap = eng.compute(sym, frames)
        last = eng.compute_series(sym, frames).row(-1, named=True)
        for col in ("ret_5m", "return_z", "volume_z", "volatility_z", "beta_market"):
            assert getattr(snap, col).value == pytest.approx(last[col], rel=1e-7), col
        for col in ("beta_sector", "market_residual_z", "sector_residual_z", "sector_residual"):
            assert getattr(snap, col).value == pytest.approx(last[col], rel=1e-7), col
        assert snap.volume_z_method == last["volume_z_method"] == "tod"
