"""Tests for beta-adjusted residuals and residual z-scores."""

import math
from datetime import UTC, datetime, timedelta

import polars as pl

from app.market.features.residual import add_residual, add_residual_z


def _frame(**cols: list) -> pl.DataFrame:
    n = len(next(iter(cols.values())))
    t0 = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
    ts = [t0 + timedelta(minutes=i) for i in range(n)]
    return pl.DataFrame(
        {"timestamp": ts, **{k: pl.Series(k, v, dtype=pl.Float64) for k, v in cols.items()}}
    )


def _resid(stock: float, bench: float, beta: float | None) -> float | None:
    df = _frame(s=[stock], b=[bench], beta=[beta])
    return add_residual(df, "s", "b", "beta", "r")["r"][0]


def test_beta_one_in_line_move_is_tiny() -> None:
    r = _resid(-0.04, -0.038, 1.0)
    assert r is not None and math.isclose(r, -0.002, abs_tol=1e-12)


def test_idiosyncratic_move_is_large() -> None:
    r = _resid(-0.04, -0.005, 1.0)
    assert r is not None and math.isclose(r, -0.035, abs_tol=1e-12)
    assert abs(r) > 10 * abs(_resid(-0.04, -0.038, 1.0))  # type: ignore[arg-type]


def test_beta_scales_benchmark() -> None:
    r = _resid(-0.04, -0.02, 2.0)
    assert r is not None and math.isclose(r, 0.0, abs_tol=1e-12)


def test_null_beta_is_null_no_beta_one_fallback() -> None:
    assert _resid(-0.04, -0.038, None) is None


def test_any_null_or_nonfinite_input_is_null() -> None:
    assert _resid(-0.04, None, 1.0) is None  # type: ignore[arg-type]
    assert _resid(None, -0.01, 1.0) is None  # type: ignore[arg-type]
    assert _resid(-0.04, float("nan"), 1.0) is None
    assert _resid(-0.04, -0.01, float("inf")) is None


def test_add_residual_preserves_rows_and_columns() -> None:
    df = _frame(s=[0.01, 0.02, 0.03], b=[0.01, None, 0.01], beta=[None, 1.0, 1.0])
    out = add_residual(df, "s", "b", "beta", "r")
    assert out.height == 3 and out["timestamp"].to_list() == df["timestamp"].to_list()
    assert out["r"].to_list()[0] is None and out["r"].to_list()[1] is None
    assert math.isclose(out["r"][2], 0.02)


def test_residual_z_warmup_and_value() -> None:
    vals = [0.001, -0.001, 0.002, -0.002, 0.001, 0.05]
    out = add_residual_z(_frame(r=vals), "r", "z", window=5, min_periods=5)
    z = out["z"].to_list()
    assert z[:5] == [None] * 5  # need 5 prior samples; first with 5 prior is index 5
    prior = vals[:5]
    mean = sum(prior) / 5
    std = math.sqrt(sum((p - mean) ** 2 for p in prior) / 4)
    assert math.isclose(z[5], (0.05 - mean) / std, rel_tol=1e-9)
    assert z[5] > 5


def test_residual_z_zero_variance_is_null_not_inf() -> None:
    vals = [0.001] * 8 + [0.05]
    z = add_residual_z(_frame(r=vals), "r", "z", window=5, min_periods=3)["z"].to_list()
    assert all(v is None for v in z)


def test_residual_z_null_current_or_all_null() -> None:
    vals = [0.001, -0.001, 0.002, -0.002, None, 0.003, 0.001]
    z = add_residual_z(_frame(r=vals), "r", "z", window=5, min_periods=3)["z"].to_list()
    assert z[4] is None
    assert z[5] is not None and math.isfinite(z[5])
    empty = add_residual_z(_frame(r=[None, None, None]), "r", "z", window=3, min_periods=2)
    assert empty["z"].to_list() == [None] * 3


def test_residual_z_never_nan_or_inf() -> None:
    vals = [0.0, 0.0, 0.0, 1e-300, 1e300, float("nan"), float("inf"), 0.01, -0.01, 0.02]
    z = add_residual_z(_frame(r=vals), "r", "z", window=4, min_periods=2)["z"].to_list()
    assert all(v is None or math.isfinite(v) for v in z)


def test_residual_z_no_lookahead() -> None:
    base = [0.001, -0.002, 0.003, -0.001, 0.002, 0.001, -0.003, 0.002]
    short = add_residual_z(_frame(r=base), "r", "z", window=4, min_periods=3)["z"].to_list()
    longer = add_residual_z(_frame(r=[*base, 0.9, -0.9, 0.5]), "r", "z", window=4, min_periods=3)[
        "z"
    ].to_list()
    assert longer[: len(base)] == short


def test_residual_z_excludes_current_value() -> None:
    a = [0.001, -0.001, 0.002, -0.002, 0.001, 0.01]
    b = [*a[:-1], 0.5]  # only the current row differs
    za = add_residual_z(_frame(r=a), "r", "z", window=5, min_periods=5)["z"].to_list()
    zb = add_residual_z(_frame(r=b), "r", "z", window=5, min_periods=5)["z"].to_list()
    assert za[5] is not None and zb[5] is not None and zb[5] > za[5]
    prior = a[:5]
    mean = sum(prior) / 5
    std = math.sqrt(sum((p - mean) ** 2 for p in prior) / 4)
    assert math.isclose(zb[5], (0.5 - mean) / std, rel_tol=1e-9)
