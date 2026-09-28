"""Deterministic replay scenario -> REAL FeatureEngine + MarketShockDetector (no pipeline, no DB).

Evaluation points are visited strictly in timestamp order. At every NEW closed 1m bar of NVDA / AMD
selected by the evaluation plan, the feature snapshot is computed from each symbol's frame
truncated to bars with ``timestamp <= that bar`` (a prefix of the timestamp-ordered history, i.e. no
lookahead, asserted per call) and fed to the detector. Feature computation is stateless, so it runs
in parallel single-threaded worker processes; the stateful detector consumes results in order.

Each ``FeatureEngine.compute`` costs ~50 ms, so coverage is planned (see ``shock_plan``):

* prior session 6 (first session with 5 prior days, i.e. the first "tod" session): every 5th bar
* shock day, NVDA and AMD: EVERY bar up to ``DENSE_END_MIN`` (covers the whole pre-shock period,
  the shock and the 15 min cooldown window), every 5th bar afterwards.

FINDING (see test_first_nvda_emission_*): ``expected_shock_at`` is the START of the 5th shocked bar
(5-bar return complete), but the scenario is so violent per bar (-0.9% on 8x volume, ~11 sigma per
1m bar) that the real detector already fires on the FIRST shocked bar, ``SHOCK_BARS - 1`` minutes
earlier. So the strict "no emission" boundary is the shock START, and detection must happen no
later than ``expected_shock_at``.
"""

from __future__ import annotations

import bisect
import functools
import os
import time
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import pairwise
from multiprocessing import get_context

import polars as pl
import pytest

from app.market.features.engine import FeatureEngine
from app.market.fixtures import (
    PRIOR_SESSION_DATES,
    SESSION_MINUTES,
    SHOCK_BARS,
    SHOCK_DAY,
    SHOCK_SYMBOL,
    ShockScenario,
    build_normal_scenario,
    build_shock_scenario,
)
from app.market.settings import FeatureConfig, ShockConfig
from app.market.shock.detector import MarketShockDetector, ShockDecision
from app.market.shock.events import build_shock_event
from app.market.types import Bar, ProviderName, ShockDirection, ShockLevel, SymbolFeatures
from app.market.universe import load_universe
from app.schemas.event import EventCreate, SourceType

EVAL_SYMBOLS = ("NVDA", "AMD")
DENSE_END_MIN = 175  # shock start 150 + 5 shocked bars + 15 min cooldown window + margin
COOLDOWN = timedelta(seconds=ShockConfig().cooldown_seconds)
UNIVERSE = ("NVDA", "AMD", "SOXX", "SPY")
SIXTH_SESSION = PRIOR_SESSION_DATES[5]  # first session with 5 prior sessions => "tod" volume z
FRAME_SCHEMA = {
    "timestamp": pl.Datetime("us", "UTC"),
    "open": pl.Float64,
    "high": pl.Float64,
    "low": pl.Float64,
    "close": pl.Float64,
    "volume": pl.Float64,
}


@dataclass(frozen=True)
class Step:
    symbol: str
    ts: datetime
    features: SymbolFeatures
    decision: ShockDecision

    @property
    def minute(self) -> int:
        return int((self.ts - self.ts.replace(hour=13, minute=30)).total_seconds() // 60)


def _frame(bars: list[Bar]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "timestamp": [b.timestamp for b in bars],
            "open": [b.open for b in bars],
            "high": [b.high for b in bars],
            "low": [b.low for b in bars],
            "close": [b.close for b in bars],
            "volume": [b.volume for b in bars],
        },
        schema=FRAME_SCHEMA,
    )


Plan = Callable[[str, datetime, int], bool]


def shock_plan(symbol: str, ts: datetime, minute: int) -> bool:
    """Coverage for the shock scenario (see module docstring)."""
    if ts.date() == SHOCK_DAY:
        return minute <= DENSE_END_MIN or minute % 5 == 0
    return ts.date() == SIXTH_SESSION and minute % 5 == 0


def normal_plan(symbol: str, ts: datetime, minute: int) -> bool:
    """Normal scenario: NVDA dense around where the shock would be, sparse elsewhere."""
    if ts.date() == SHOCK_DAY:
        if symbol == SHOCK_SYMBOL and 140 <= minute <= DENSE_END_MIN:
            return True
        return minute % 5 == 0
    return False


def light_plan(symbol: str, ts: datetime, minute: int) -> bool:
    """Cheap subset of shock_plan used for the determinism re-run."""
    return shock_plan(symbol, ts, minute) and ts.date() == SHOCK_DAY and 140 <= minute <= 170


def _build(kind: str) -> ShockScenario:
    return build_shock_scenario() if kind == "shock" else build_normal_scenario()


@functools.cache
def _full_frames(kind: str) -> tuple[dict[str, pl.DataFrame], dict[str, list[datetime]]]:
    """Per-symbol 1m frames of the whole scenario, bars already in timestamp order."""
    by_sym: dict[str, list[Bar]] = {s: [] for s in UNIVERSE}
    for b in _build(kind).bars:
        by_sym[b.symbol].append(b)
    frames = {s: _frame(bars) for s, bars in by_sym.items()}
    return frames, {s: [b.timestamp for b in bars] for s, bars in by_sym.items()}


def _features_at(kind: str, symbol: str, ts: datetime) -> SymbolFeatures:
    """Features for ``symbol`` using ONLY bars with timestamp <= ``ts`` (no lookahead)."""
    frames, stamps = _full_frames(kind)
    seen = {s: frames[s].head(bisect.bisect_right(stamps[s], ts)) for s in UNIVERSE}
    assert all(f.height == 0 or f["timestamp"][-1] <= ts for f in seen.values())
    assert seen[symbol]["timestamp"][-1] == ts  # a NEW closed bar of this symbol
    engine = FeatureEngine(load_universe(), FeatureConfig())
    feats = engine.compute(symbol, seen)
    assert feats.as_of == ts
    return feats


def _compute_chunk(kind: str, points: list[tuple[str, datetime]]) -> list[SymbolFeatures]:
    return [_features_at(kind, sym, ts) for sym, ts in points]  # runs in a worker process


def _points(kind: str, plan: Plan) -> list[tuple[str, datetime]]:
    """Evaluation points (symbol, bar ts) in timestamp order, selected by ``plan``."""
    _, stamps = _full_frames(kind)
    order = sorted(set(stamps["NVDA"]))
    assert stamps["NVDA"] == order and stamps["AMD"] == order
    day_start: dict = {}
    out: list[tuple[str, datetime]] = []
    for ts in order:
        minute = int((ts - day_start.setdefault(ts.date(), ts)).total_seconds() // 60)
        out.extend((sym, ts) for sym in EVAL_SYMBOLS if plan(sym, ts, minute))
    return out


def _compute_all(kind: str, points: list[tuple[str, datetime]]) -> list[SymbolFeatures]:
    """Features are stateless per point, so they are computed in parallel single-threaded
    worker processes (polars' shared thread pool oversubscribes badly otherwise); the detector,
    which IS stateful, still consumes them strictly in timestamp order in the parent."""
    workers = min(os.cpu_count() or 1, 8)
    chunks = [c for i in range(workers * 3) if (c := list(range(i, len(points), workers * 3)))]
    if workers > 1:
        prev = os.environ.get("POLARS_MAX_THREADS")
        os.environ["POLARS_MAX_THREADS"] = "1"  # inherited by the spawned workers
        try:
            with ProcessPoolExecutor(max_workers=workers, mp_context=get_context("spawn")) as ex:
                futs = [
                    ex.submit(_compute_chunk, kind, [points[i] for i in c]) for c in chunks if c
                ]
                results = [f.result() for f in futs]
        except (OSError, RuntimeError):  # pragma: no cover - sandbox without process spawning
            results = [_compute_chunk(kind, [points[i] for i in c]) for c in chunks]
        finally:
            if prev is None:
                os.environ.pop("POLARS_MAX_THREADS", None)
            else:
                os.environ["POLARS_MAX_THREADS"] = prev
    else:  # pragma: no cover
        results = [_compute_chunk(kind, [points[i] for i in c]) for c in chunks]
    feats: list[SymbolFeatures | None] = [None] * len(points)
    for c, res in zip([c for c in chunks], results, strict=True):
        for i, f in zip(c, res, strict=True):
            feats[i] = f
    assert all(f is not None for f in feats)
    return feats  # type: ignore[return-value]


def run_scenario(kind: str, plan: Plan) -> list[Step]:
    """Replay a scenario through the real engine + detector; ``kind`` is 'shock' or 'normal'."""
    points = _points(kind, plan)
    detector = MarketShockDetector(ShockConfig())
    return [
        Step(sym, ts, f, detector.evaluate(f))
        for (sym, ts), f in zip(points, _compute_all(kind, points), strict=True)
    ]


@pytest.fixture(scope="module")
def shock_scenario() -> ShockScenario:
    return build_shock_scenario()


@pytest.fixture(scope="module")
def shock_run(shock_scenario: ShockScenario) -> tuple[list[Step], float]:
    t0 = time.perf_counter()
    steps = run_scenario("shock", shock_plan)
    return steps, time.perf_counter() - t0


def _emits(steps: list[Step], symbol: str | None = None) -> list[Step]:
    return [s for s in steps if s.decision.emit and (symbol is None or s.symbol == symbol)]


def _start(sc: ShockScenario) -> datetime:
    """Timestamp of the FIRST shocked bar (expected_shock_at is the 5th)."""
    assert sc.expected_shock_at is not None
    return sc.expected_shock_at - timedelta(minutes=SHOCK_BARS - 1)


def test_no_emission_before_shock(shock_scenario: ShockScenario, shock_run) -> None:
    steps, _ = shock_run
    expected, start = shock_scenario.expected_shock_at, _start(shock_scenario)
    assert expected is not None
    nvda_day = [s for s in steps if s.ts.date() == SHOCK_DAY and s.symbol == SHOCK_SYMBOL]
    # every NVDA bar of the shock day up to the end of the dense window was evaluated
    assert [s.minute for s in nvda_day if s.minute <= DENSE_END_MIN] == list(
        range(DENSE_END_MIN + 1)
    )
    amd_day = [s for s in steps if s.ts.date() == SHOCK_DAY and s.symbol == "AMD"]
    assert [s.minute for s in amd_day if s.minute <= DENSE_END_MIN] == list(
        range(DENSE_END_MIN + 1)
    )
    prior6 = [s for s in steps if s.ts.date() == SIXTH_SESSION]
    assert len(prior6) == 2 * len(range(0, SESSION_MINUTES, 5))
    # strict: no emission on ANY evaluated bar before the shock starts, nor (weaker, as specified)
    # before expected_shock_at on a bar that is not part of the shock
    bad = [
        (s.symbol, s.ts.isoformat(), s.decision.reason)
        for s in steps
        if s.ts < start and s.decision.emit
    ]
    assert not bad, f"emission before the shock start: {bad}"
    # ready + "tod" volume method is really exercised on the shock day, and quiet bars stay quiet
    ready = [s for s in steps if s.ts.date() == SHOCK_DAY and s.features.volume_z.value is not None]
    assert ready and all(s.features.volume_z_method == "tod" for s in ready)
    pre = [s for s in nvda_day if s.ts < start and s.decision.assessment.ready]
    assert pre
    print(f"\nNVDA pre-shock max score={max(s.decision.assessment.score for s in pre):.3f}")
    assert max(s.decision.assessment.score for s in pre) < ShockConfig().shock_threshold


def test_first_nvda_emission_at_shock(shock_scenario: ShockScenario, shock_run) -> None:
    steps, _ = shock_run
    expected, start = shock_scenario.expected_shock_at, _start(shock_scenario)
    assert expected is not None
    nvda = _emits(steps, SHOCK_SYMBOL)
    assert nvda, "NVDA never emitted a shock"
    first = nvda[0]
    a = first.decision.assessment
    print(
        f"\nFIRST NVDA EMIT ts={first.ts.isoformat()} (shock start {start.isoformat()}, "
        f"expected_shock_at {expected.isoformat()}) score={a.score:.4f} level={a.level.value} "
        f"direction={a.direction} ready={a.ready} vol_method={first.features.volume_z_method}\n"
        f"  components={a.components}"
    )
    # detected no earlier than the shock starts, and no later than the 5-bar return completing
    # (the spec allows +2 bars after expected_shock_at; the real detector is 4 bars EARLIER).
    assert start <= first.ts <= expected + timedelta(minutes=2)
    assert first.ts <= expected
    assert a.level in (ShockLevel.SHOCK, ShockLevel.SEVERE)
    assert a.direction == ShockDirection.NEGATIVE
    assert a.ready is True
    assert first.features.volume_z_method == "tod"
    assert first.decision.reason == "emit"
    assert a.calibrated is False
    assert (first.features.ret_5m.value or 0.0) < 0


def test_amd_never_emits(shock_run) -> None:
    steps, _ = shock_run
    amd = [s for s in steps if s.symbol == "AMD"]
    assert len(amd) > 100
    assert not _emits(steps, "AMD")
    assert all(s.decision.assessment.level != ShockLevel.SEVERE for s in amd)
    assert all(s.decision.reason != "emit" for s in amd)


def test_cooldown_suppresses_repeats(shock_run) -> None:
    steps, _ = shock_run
    nvda = [s for s in steps if s.symbol == SHOCK_SYMBOL]
    emits = _emits(steps, SHOCK_SYMBOL)
    first = emits[0]
    rank = {ShockLevel.SHOCK: 1, ShockLevel.SEVERE: 2}
    in_window = [s for s in nvda if first.ts < s.ts < first.ts + COOLDOWN]
    assert len(in_window) >= 14  # dense evaluation covers the whole cooldown window
    for s in in_window:  # a repeat inside the window is only allowed on level escalation
        if s.decision.emit:
            assert rank[s.decision.assessment.level] > rank[first.decision.assessment.level]
    suppressed = [s for s in in_window if s.decision.reason == "cooldown"]
    emit_log = [(s.ts.strftime("%H:%M"), s.decision.assessment.level.value) for s in emits]
    print(f"\nNVDA emits={emit_log} cooldown-suppressed in window={len(suppressed)}")
    assert suppressed, "expected at least one cooldown-suppressed bar right after the shock"
    for (
        s
    ) in suppressed:  # suppressed bars were genuinely emit-worthy (ready, >= SHOCK, directional)
        a = s.decision.assessment
        assert a.ready and a.level in rank and a.direction == ShockDirection.NEGATIVE
    for prev, nxt in pairwise(emits):  # later emits respect the window
        assert (
            nxt.ts - prev.ts >= COOLDOWN
            or rank[nxt.decision.assessment.level] > rank[prev.decision.assessment.level]
        )


def test_normal_scenario_emits_nothing() -> None:
    normal = build_normal_scenario()
    assert normal.expected_shock_at is None
    steps = run_scenario("normal", normal_plan)
    assert {s.symbol for s in steps} == {"NVDA", "AMD"}
    assert sum(1 for s in steps if s.symbol == SHOCK_SYMBOL and 150 <= s.minute <= 170) == 21
    assert not _emits(steps)
    ready = [s for s in steps if s.decision.assessment.ready]
    assert ready
    peak = max(s.decision.assessment.score for s in ready)
    print(f"\nNORMAL steps={len(steps)} peak ready score={peak:.4f}")
    assert peak < ShockConfig().watch_threshold + 0.2  # far below the 0.55 emit threshold


def test_shock_event_valid_deterministic_mock(shock_run) -> None:
    steps, _ = shock_run
    first = _emits(steps, SHOCK_SYMBOL)[0]
    ev = build_shock_event(first.decision.assessment, first.features, ProviderName.REPLAY)
    assert isinstance(ev, EventCreate)
    EventCreate.model_validate(ev.model_dump(mode="json"))  # round-trips through validation
    assert ev.is_mock is True
    assert ev.source_type == SourceType.MARKET
    assert ev.companies == [SHOCK_SYMBOL]
    assert ev.metadata["calibrated"] is False
    assert ev.metadata["direction"] == "negative"
    assert ev.metadata["volume_z_method"] == "tod"
    assert ev.timestamp == first.ts
    assert ev.id == f"evt_mkt_nvda_{first.ts:%Y%m%d%H%M}_neg"
    ev2 = build_shock_event(first.decision.assessment, first.features, ProviderName.REPLAY)
    assert ev2.id == ev.id
    assert ev2.model_dump() == ev.model_dump()


def _signature(steps: list[Step]) -> dict[tuple[str, datetime], tuple]:
    return {
        (s.symbol, s.ts): (
            s.decision.emit,
            s.decision.reason,
            s.decision.assessment.score,
            s.decision.assessment.level,
            s.decision.assessment.direction,
            s.features.model_dump(),
        )
        for s in steps
    }


def test_determinism(shock_run) -> None:
    steps, _ = shock_run
    assert build_shock_scenario().bars == build_shock_scenario().bars  # generation is bit-identical
    again = run_scenario("shock", light_plan)
    assert again
    ref = _signature(steps)
    got = _signature(again)
    assert set(got) <= set(ref)
    assert {k: ref[k] for k in got} == got  # same features, scores, levels, emit/reason decisions
    assert any(v[0] for v in got.values())  # the compared window contains the emission


def test_runtime_budget(shock_run) -> None:
    steps, elapsed = shock_run
    print(f"\nRUNTIME shock run={elapsed:.1f}s for {len(steps)} evaluations")
    assert elapsed < 20.0
