from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import polars as pl
import pytest

from app.market.features.returns import add_log_return

T0 = datetime(2025, 3, 3, 14, 30, tzinfo=UTC)


def _ts(i: int) -> datetime:
    return T0 + timedelta(minutes=i)


def _frame(closes: list[float | None], idx: list[int] | None = None) -> pl.DataFrame:
    idx = idx if idx is not None else list(range(len(closes)))
    return pl.DataFrame(
        {"timestamp": [_ts(i) for i in idx], "close": closes},
        schema={"timestamp": pl.Datetime("us", "UTC"), "close": pl.Float64},
    )


def _vals(df: pl.DataFrame, col: str = "r") -> list[float | None]:
    return df[col].to_list()


def test_known_value() -> None:
    out = add_log_return(_frame([100.0, 105.0]), 1, "r")
    assert _vals(out) == [None, pytest.approx(math.log(105 / 100))]


@pytest.mark.parametrize("h", [1, 5, 15])
def test_horizons_null_head_and_values(h: int) -> None:
    closes = [100.0 + i for i in range(30)]
    out = add_log_return(_frame(closes), h, "r")
    vals = _vals(out)
    assert all(v is None for v in vals[:h])
    for i in range(h, 30):
        assert vals[i] == pytest.approx(math.log(closes[i] / closes[i - h]))


def test_shorter_than_horizon_all_null() -> None:
    out = add_log_return(_frame([1.0, 2.0, 3.0]), 5, "r")
    assert _vals(out) == [None, None, None]


def test_unsorted_input_sorted_output() -> None:
    df = _frame([110.0, 100.0, 105.0], idx=[2, 0, 1])
    out = add_log_return(df, 1, "r")
    assert out["close"].to_list() == [100.0, 105.0, 110.0]
    assert _vals(out) == [
        None,
        pytest.approx(math.log(1.05)),
        pytest.approx(math.log(110 / 105)),
    ]


def test_duplicate_timestamps_keep_last() -> None:
    df = _frame([100.0, 999.0, 105.0], idx=[0, 1, 1])
    out = add_log_return(df, 1, "r")
    assert out.height == 2
    assert out["close"].to_list() == [100.0, 105.0]
    assert _vals(out)[1] == pytest.approx(math.log(1.05))


def test_missing_bar_not_forward_filled() -> None:
    df = _frame([100.0, 101.0, 103.0], idx=[0, 1, 3])  # minute 2 missing
    out = add_log_return(df, 1, "r")
    assert out.height == 3  # no gap row inserted
    assert out["timestamp"].to_list() == [_ts(0), _ts(1), _ts(3)]
    assert _vals(out)[2] == pytest.approx(math.log(103 / 101))


@pytest.mark.parametrize("bad", [0.0, -5.0])
def test_non_positive_price_gives_null_not_inf_nan(bad: float) -> None:
    out = add_log_return(_frame([100.0, bad, 100.0, 110.0]), 1, "r")
    vals = _vals(out)
    assert vals[:3] == [None, None, None]  # bad as numerator and as denominator
    assert vals[3] == pytest.approx(math.log(1.1))
    assert all(v is None or math.isfinite(v) for v in vals)


def test_null_and_nan_prices_give_null() -> None:
    out = add_log_return(_frame([100.0, None, float("nan"), 100.0, 101.0]), 1, "r")
    vals = _vals(out)
    assert vals[1:4] == [None, None, None]
    assert vals[4] == pytest.approx(math.log(1.01))
    assert all(v is None or math.isfinite(v) for v in vals)


def test_empty_frame() -> None:
    out = add_log_return(_frame([]), 1, "r")
    assert out.height == 0
    assert out.schema["r"] == pl.Float64


def test_invalid_horizon() -> None:
    with pytest.raises(ValueError):
        add_log_return(_frame([1.0]), 0, "r")


def test_preserves_input_and_columns() -> None:
    df = _frame([100.0, 101.0])
    before = df.clone()
    out = add_log_return(df, 1, "ret_1m")
    assert df.equals(before)
    assert out.columns == ["timestamp", "close", "ret_1m"]


def test_no_lookahead_appending_future_rows() -> None:
    closes = [100.0 + math.sin(i) * 3 for i in range(40)]
    base = add_log_return(_frame(closes), 5, "r")
    extended = add_log_return(_frame([*closes, 1.0, 500.0, 0.0, 90.0]), 5, "r")
    assert _vals(extended)[:40] == _vals(base)
