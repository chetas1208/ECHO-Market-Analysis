from __future__ import annotations

import math
import time
from collections import defaultdict
from datetime import UTC, datetime, timedelta

import pytest

from app.market import fixtures as fx
from app.market.types import Bar, Interval, ProviderName


@pytest.fixture(scope="module")
def shock() -> fx.ShockScenario:
    return fx.build_shock_scenario()


@pytest.fixture(scope="module")
def normal() -> fx.ShockScenario:
    return fx.build_normal_scenario()


def _series(bars: list[Bar], symbol: str) -> list[Bar]:
    return [b for b in bars if b.symbol == symbol]


def _ret5(closes: list[float], i: int) -> float:
    return math.log(closes[i] / closes[i - 5])


def test_deterministic() -> None:
    assert fx.build_shock_scenario() == fx.build_shock_scenario()
    assert fx.build_normal_scenario() == fx.build_normal_scenario()


def test_generation_fast() -> None:
    t0 = time.perf_counter()
    fx.build_shock_scenario()
    assert time.perf_counter() - t0 < 1.0


def test_ordering_and_counts(shock: fx.ShockScenario) -> None:
    keys = [(b.timestamp, b.symbol) for b in shock.bars]
    assert keys == sorted(keys)
    assert len(set(keys)) == len(keys)
    assert shock.universe_symbols == ["NVDA", "AMD", "SOXX", "SPY"]
    for sym in shock.universe_symbols:
        assert len(_series(shock.bars, sym)) == 7 * 390 >= 6 * 390
    assert len(shock.bars) == 4 * 7 * 390


def test_bar_validity(shock: fx.ShockScenario) -> None:
    for b in shock.bars:
        assert b.source == ProviderName.REPLAY
        assert b.interval == Interval.M1
        assert b.low <= min(b.open, b.close) and b.high >= max(b.open, b.close)
        assert b.volume > 0
        assert b.timestamp.tzinfo is not None and b.timestamp.utcoffset() == timedelta(0)
        assert b.received_at is None


def test_timestamps_within_regular_sessions(shock: fx.ShockScenario) -> None:
    per_day: dict[object, set[datetime]] = defaultdict(set)
    for b in _series(shock.bars, "SPY"):
        per_day[b.timestamp.date()].add(b.timestamp)
    assert sorted(per_day) == [*fx.PRIOR_SESSION_DATES, fx.SHOCK_DAY]
    assert len(fx.PRIOR_SESSION_DATES) == 6
    for d, stamps in per_day.items():
        assert d.weekday() < 5
        open_ts = datetime(d.year, d.month, d.day, 13, 30, tzinfo=UTC)
        assert min(stamps) == open_ts
        assert max(stamps) == open_ts + timedelta(minutes=389)  # last bar starts 19:59Z
        assert len(stamps) == 390


def test_same_timestamps_all_symbols(shock: fx.ShockScenario) -> None:
    ref = [b.timestamp for b in _series(shock.bars, "SPY")]
    for sym in ("NVDA", "AMD", "SOXX"):
        assert [b.timestamp for b in _series(shock.bars, sym)] == ref


def test_u_shaped_volume(normal: fx.ShockScenario) -> None:
    nv = _series(normal.bars, "NVDA")
    by_min: dict[int, list[float]] = defaultdict(list)
    for i, b in enumerate(nv):
        by_min[i % 390].append(b.volume)
    avg = {m: sum(v) / len(v) for m, v in by_min.items()}
    midday = sum(avg[m] for m in range(180, 210)) / 30
    assert avg[0] / midday > 3.0
    assert avg[389] / midday > 3.0


def test_shock_move_and_volume(shock: fx.ShockScenario) -> None:
    assert shock.shock_symbol == "NVDA"
    assert shock.expected_shock_at == datetime(2026, 9, 16, 13, 30, tzinfo=UTC) + timedelta(
        minutes=154
    )
    nv = _series(shock.bars, "NVDA")
    idx = next(i for i, b in enumerate(nv) if b.timestamp == shock.expected_shock_at)
    closes = [b.close for b in nv]
    assert _ret5(closes, idx) == pytest.approx(math.log(1 - 0.045), abs=1e-9)
    # each of the 5 bars is a down bar
    assert all(closes[i] < closes[i - 1] for i in range(idx - 4, idx + 1))
    # volume multiple vs. same minute in prior sessions
    day_start = idx - 154
    for k in range(150, 155):
        prior = [nv[d * 390 + k].volume for d in range(6)]
        assert nv[day_start + k].volume / (sum(prior) / len(prior)) > 5.0
    # 5-bar return is abnormal relative to NVDA's own history
    hist = [_ret5(closes, i) for i in range(5, day_start + 100)]
    sd = (sum(r * r for r in hist) / len(hist)) ** 0.5
    assert abs(_ret5(closes, idx)) > 10 * sd


def test_benchmarks_flat_during_shock(shock: fx.ShockScenario) -> None:
    idx = 6 * 390 + 154
    for sym in ("SOXX", "SPY", "AMD"):
        closes = [b.close for b in _series(shock.bars, sym)]
        assert abs(_ret5(closes, idx)) < 0.006
    for sym in ("SOXX", "SPY"):
        vols = [b.volume for b in _series(shock.bars, sym)]
        prior = [vols[d * 390 + 152] for d in range(6)]
        assert vols[6 * 390 + 152] / (sum(prior) / 6) < 3.0


def test_normal_has_no_shock(normal: fx.ShockScenario) -> None:
    assert normal.expected_shock_at is None
    for sym in normal.universe_symbols:
        bars = _series(normal.bars, sym)
        closes = [b.close for b in bars]
        for i in range(5, len(closes)):
            if i % 390 < 5:  # skip windows spanning the overnight gap
                continue
            assert abs(_ret5(closes, i)) < 0.015, (sym, i)
    nv = _series(normal.bars, "NVDA")
    midday = [b.volume for i, b in enumerate(nv) if 60 <= i % 390 <= 330]
    assert max(midday) / (sum(midday) / len(midday)) < 3.0


def test_shock_equals_normal_outside_window(
    shock: fx.ShockScenario, normal: fx.ShockScenario
) -> None:
    s = {(b.symbol, b.timestamp): b for b in shock.bars}
    n = {(b.symbol, b.timestamp): b for b in normal.bars}
    assert s.keys() == n.keys()
    diff_syms = {k[0] for k in s if s[k] != n[k]}
    assert diff_syms == {"NVDA"}
    first_diff = min(k[1] for k in s if s[k] != n[k])
    assert first_diff == datetime(2026, 9, 16, 13, 30, tzinfo=UTC) + timedelta(minutes=150)


def test_custom_params() -> None:
    sc = fx.build_shock_scenario(shock_at_minute=100, magnitude=-0.03, volume_multiple=6.0)
    assert sc.expected_shock_at == datetime(2026, 9, 16, 13, 30, tzinfo=UTC) + timedelta(
        minutes=104
    )
    closes = [b.close for b in _series(sc.bars, "NVDA")]
    assert _ret5(closes, 6 * 390 + 104) == pytest.approx(math.log(1 - 0.03), abs=1e-9)
    up = fx.build_shock_scenario(magnitude=0.05)
    closes = [b.close for b in _series(up.bars, "NVDA")]
    assert _ret5(closes, 6 * 390 + 154) == pytest.approx(math.log(1.05), abs=1e-9)


@pytest.mark.parametrize(
    "kwargs",
    [{"shock_at_minute": 0}, {"shock_at_minute": 386}, {"magnitude": 0.0}, {"magnitude": -1.0}],
)
def test_invalid_params(kwargs: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        fx.build_shock_scenario(**kwargs)  # type: ignore[arg-type]
