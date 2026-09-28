from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.market.settings import ShockConfig
from app.market.shock.detector import MarketShockDetector
from app.market.types import (
    FeatureStatus,
    FeatureValue,
    ShockDirection,
    ShockLevel,
    SymbolFeatures,
)

T0 = datetime(2025, 3, 10, 15, 0, tzinfo=UTC)
MIN = timedelta(minutes=1)


def fv(v: float | None) -> FeatureValue:
    return FeatureValue(
        value=v, status=FeatureStatus.READY if v is not None else FeatureStatus.UNAVAILABLE
    )


def feats(
    *,
    symbol: str = "NVDA",
    as_of: datetime = T0,
    ret_z: float = 0.0,
    vol_z: float = 0.0,
    volat_z: float = 0.0,
    sector_z: float = 0.0,
    market_z: float = 0.0,
    sector_res: float = -0.03,
    ready: bool = True,
) -> SymbolFeatures:
    return SymbolFeatures(
        symbol=symbol,
        as_of=as_of,
        price=100.0,
        ret_5m=fv(sector_res),
        return_z=fv(ret_z),
        volume_z=fv(vol_z),
        volatility_z=fv(volat_z),
        market_residual=fv(sector_res),
        market_residual_z=fv(market_z),
        sector_residual=fv(sector_res),
        sector_residual_z=fv(sector_z),
        overall_status=FeatureStatus.READY if ready else FeatureStatus.WARMING_UP,
    )


def shock(as_of: datetime = T0, **kw) -> SymbolFeatures:
    """Stock-specific shock: default weights/cap -> score 0.65 (SHOCK)."""
    return feats(as_of=as_of, ret_z=-4, vol_z=4, volat_z=4, sector_z=-4, market_z=-3, **kw)


def severe(as_of: datetime = T0, **kw) -> SymbolFeatures:
    """Score ~0.85 (SEVERE)."""
    return feats(as_of=as_of, ret_z=-5, vol_z=6, volat_z=5, sector_z=-5, market_z=-4, **kw)


@pytest.fixture
def det() -> MarketShockDetector:
    return MarketShockDetector(ShockConfig())


def test_normal_movement_does_not_trigger(det):
    d = det.evaluate(feats(ret_z=0.5, vol_z=0.4, volat_z=0.6, sector_z=0.3, market_z=0.2))
    assert d.emit is False
    assert d.reason == "below_threshold"
    assert d.assessment.level == ShockLevel.NONE
    assert d.assessment.score < 0.15
    assert d.assessment.calibrated is False


def test_price_move_without_volume_confirmation_exact_score(det):
    # ret 6/6*.3 + vol 0.5/6*.2 + volat 1/6*.2 + sector 3/6*.2 + market 2/6*.1 = 0.48333
    d = det.evaluate(feats(ret_z=-6, vol_z=0.5, volat_z=1, sector_z=-3, market_z=-2))
    assert d.assessment.score == pytest.approx(0.3 + 0.5 / 6 * 0.2 + 0.2 / 6 + 0.1 + 0.1 / 3)
    assert d.assessment.level == ShockLevel.WATCH
    assert (d.emit, d.reason) == (False, "below_threshold")


def test_price_move_with_all_else_confirmed_but_no_volume_still_emits_per_config(det):
    # Volume is a weighted component, NOT a hard gate: 0.30+0+.1667+.1667+.0667 = 0.70 (SHOCK)
    d = det.evaluate(feats(ret_z=-6, vol_z=0.0, volat_z=5, sector_z=-5, market_z=-4))
    assert d.assessment.components["volume"] == 0.0
    assert d.assessment.score == pytest.approx(0.3 + 5 / 6 * 0.2 * 2 + 4 / 6 * 0.1)
    assert d.emit is True
    # Same move with volume weight dominant (stricter config) does not emit.
    strict = ShockConfig(
        weights={"ret": 0.1, "volume": 0.6, "volatility": 0.1, "sector": 0.1, "market": 0.1}
    )
    d2 = MarketShockDetector(strict).evaluate(
        feats(ret_z=-6, vol_z=0.0, volat_z=5, sector_z=-5, market_z=-4)
    )
    assert d2.emit is False and d2.reason == "below_threshold"


def test_negative_volume_z_counts_as_zero(det):
    d = det.evaluate(feats(ret_z=-6, vol_z=-6, volat_z=5, sector_z=-5, market_z=-4))
    assert d.assessment.components["volume"] == 0.0


def test_sector_wide_high_volume_scores_lower_and_does_not_emit(det):
    sector_wide = det.evaluate(feats(ret_z=-4, vol_z=4, volat_z=4, sector_z=0.0, market_z=-3))
    specific = MarketShockDetector(ShockConfig()).evaluate(
        feats(ret_z=-4, vol_z=4, volat_z=4, sector_z=-4, market_z=-3)
    )
    assert sector_wide.assessment.score < specific.assessment.score
    assert sector_wide.assessment.score < 0.55
    assert sector_wide.emit is False
    assert sector_wide.reason == "below_threshold"
    assert specific.emit is True


def test_stock_specific_shock_emits_negative(det):
    d = det.evaluate(shock())
    assert d.emit is True and d.reason == "emit"
    assert d.assessment.level == ShockLevel.SHOCK
    assert d.assessment.direction == ShockDirection.NEGATIVE
    assert d.assessment.ready is True
    assert det.stats.emitted == 1


def test_positive_shock_direction(det):
    d = det.evaluate(shock(sector_res=0.03))
    assert d.emit is True
    assert d.assessment.direction == ShockDirection.POSITIVE


def test_direction_falls_back_when_sector_residual_null(det):
    f = shock().model_copy(update={"sector_residual": fv(None), "market_residual": fv(0.02)})
    assert det.evaluate(f).assessment.direction == ShockDirection.POSITIVE


def test_no_direction_never_emits(det):
    d = det.evaluate(shock(sector_res=0.0))
    assert d.assessment.direction is None
    assert d.emit is False
    assert d.reason == "no_direction"


def test_duplicate_bar_no_second_event_and_no_state_change(det):
    assert det.evaluate(shock()).emit is True
    snap = det.cooldown.snapshot()
    d = det.evaluate(shock())
    assert (d.emit, d.reason) == (False, "duplicate_bar")
    assert det.cooldown.snapshot() == snap
    assert det.stats.duplicates == 1
    assert det.stats.evaluated == 1
    assert det.stats.emitted == 1
    assert det.stats.suppressed_cooldown == 0


def test_duplicate_bar_even_when_first_eval_was_below_threshold(det):
    assert det.evaluate(feats()).reason == "below_threshold"
    assert det.evaluate(shock()).reason == "duplicate_bar"


def test_as_of_going_backwards_ignored(det):
    det.evaluate(feats(as_of=T0 + 5 * MIN))
    d = det.evaluate(shock(as_of=T0))
    assert (d.emit, d.reason) == (False, "duplicate_bar")
    assert det.cooldown.snapshot()["entries"] == []
    # forward progress still works afterwards
    assert det.evaluate(shock(as_of=T0 + 6 * MIN)).emit is True
    assert det.stats.duplicates == 1


def test_dedupe_is_per_symbol(det):
    assert det.evaluate(shock(symbol="NVDA")).emit is True
    assert det.evaluate(shock(symbol="AMD")).emit is True
    assert det.evaluate(shock(symbol="AMD")).reason == "duplicate_bar"


def test_cooldown_suppression_then_escalation_emits(det):
    assert det.evaluate(shock(as_of=T0)).emit is True
    d = det.evaluate(shock(as_of=T0 + MIN))
    assert (d.emit, d.reason) == (False, "cooldown")
    d = det.evaluate(severe(as_of=T0 + 2 * MIN))
    assert d.assessment.level == ShockLevel.SEVERE
    assert (d.emit, d.reason) == (True, "emit")
    # SEVERE then SHOCK again within cooldown: suppressed
    assert det.evaluate(shock(as_of=T0 + 3 * MIN)).reason == "cooldown"
    assert det.stats.suppressed_cooldown == 2
    assert det.stats.emitted == 2


def test_emits_again_after_cooldown_expiry(det):
    t1 = T0 + MIN
    assert det.evaluate(shock(as_of=T0)).emit is True
    assert det.evaluate(shock(as_of=t1)).reason == "cooldown"
    d = det.evaluate(shock(as_of=T0 + timedelta(seconds=det.cfg.cooldown_seconds)))
    assert (d.emit, d.reason) == (True, "emit")


def test_opposite_direction_not_suppressed_by_cooldown(det):
    assert det.evaluate(shock(as_of=T0, sector_res=-0.03)).emit is True
    d = det.evaluate(shock(as_of=T0 + MIN, sector_res=0.03))
    assert d.emit is True and d.assessment.direction == ShockDirection.POSITIVE


def test_not_ready_never_emits(det):
    d = det.evaluate(severe(ready=False))
    assert (d.emit, d.reason) == (False, "not_ready")
    assert d.assessment.ready is False
    assert d.assessment.level == ShockLevel.NONE
    assert d.assessment.score > 0.75  # score kept, but never actionable
    assert det.stats.not_ready == 1
    assert det.cooldown.snapshot()["entries"] == []


def test_stats_counters(det):
    det.evaluate(feats(as_of=T0))  # below
    det.evaluate(severe(as_of=T0 + MIN, ready=False))  # not ready
    det.evaluate(shock(as_of=T0 + 2 * MIN))  # emit
    det.evaluate(shock(as_of=T0 + 3 * MIN))  # cooldown
    det.evaluate(shock(as_of=T0 + 3 * MIN))  # duplicate
    s = det.stats
    assert (s.evaluated, s.emitted, s.suppressed_cooldown, s.duplicates, s.not_ready) == (
        4,
        1,
        1,
        1,
        1,
    )
    assert set(s.as_dict()) == {
        "evaluated",
        "emitted",
        "suppressed_cooldown",
        "duplicates",
        "not_ready",
    }


def test_deterministic_replay_same_inputs_same_decisions():
    seq = [
        feats(as_of=T0),
        shock(as_of=T0 + MIN),
        shock(as_of=T0 + 2 * MIN),
        severe(as_of=T0 + 3 * MIN),
    ]
    a, b = MarketShockDetector(ShockConfig()), MarketShockDetector(ShockConfig())
    assert [(d.emit, d.reason) for d in map(a.evaluate, seq)] == [
        (d.emit, d.reason) for d in map(b.evaluate, seq)
    ]


def test_reset_clears_state(det):
    det.evaluate(shock())
    det.reset()
    assert det.stats.evaluated == 0
    assert det.evaluate(shock()).emit is True
