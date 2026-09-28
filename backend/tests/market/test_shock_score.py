"""Tests for the heuristic shock score (pure, no I/O)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.market.settings import ShockConfig, ShockWeights
from app.market.shock.score import assess, component
from app.market.types import (
    FeatureStatus,
    FeatureValue,
    ShockDirection,
    ShockLevel,
    SymbolFeatures,
)

CFG = ShockConfig()
TS = datetime(2026, 3, 2, 15, 0, tzinfo=UTC)


def fv(v: float | None) -> FeatureValue:
    return FeatureValue(
        value=v, status=FeatureStatus.READY if v is not None else FeatureStatus.UNAVAILABLE
    )


def feats(
    *,
    ret_z: float | None = 0.0,
    vol_z: float | None = 0.0,
    vola_z: float | None = 0.0,
    sec_z: float | None = 0.0,
    mkt_z: float | None = 0.0,
    sector_residual: float | None = -0.01,
    market_residual: float | None = -0.01,
    ret_5m: float | None = -0.01,
    status: FeatureStatus = FeatureStatus.READY,
) -> SymbolFeatures:
    return SymbolFeatures(
        symbol="NVDA",
        as_of=TS,
        return_z=fv(ret_z),
        volume_z=fv(vol_z),
        volatility_z=fv(vola_z),
        sector_residual_z=fv(sec_z),
        market_residual_z=fv(mkt_z),
        sector_residual=fv(sector_residual),
        market_residual=fv(market_residual),
        ret_5m=fv(ret_5m),
        overall_status=status,
    )


def test_component_basic():
    assert component(None, 6.0) == 0.0
    assert component(3.0, 6.0) == pytest.approx(0.5)
    assert component(-3.0, 6.0) == pytest.approx(0.5)
    assert component(60.0, 6.0) == 1.0
    assert component(float("nan"), 6.0) == 0.0
    assert component(float("inf"), 6.0) == 1.0


def test_normal_movement_is_none():
    a = assess(feats(ret_z=1, vol_z=1, vola_z=1, sec_z=1, mkt_z=1), CFG)
    assert a.score == pytest.approx(1 / 6)
    assert a.level == ShockLevel.NONE
    assert a.ready is True
    assert a.calibrated is False


def test_stock_specific_shock_is_severe():
    a = assess(feats(ret_z=6, vol_z=6, vola_z=6, sec_z=6, mkt_z=6), CFG)
    assert a.score == pytest.approx(1.0)
    assert a.level == ShockLevel.SEVERE
    assert a.direction == ShockDirection.NEGATIVE
    assert set(a.components) == {"ret", "volume", "volatility", "sector", "market"}
    assert all(v == 1.0 for v in a.components.values())


def test_price_move_without_volume_confirmation():
    # ret/vola/sector/market saturated, volume z=0 -> 1 - 0.20 = 0.80 -> still SEVERE with defaults
    a = assess(feats(ret_z=6, vol_z=0, vola_z=6, sec_z=6, mkt_z=6), CFG)
    assert a.score == pytest.approx(0.80)
    assert a.level == ShockLevel.SEVERE
    # milder unconfirmed move: ret 4.5, vola 3, sector 4.5, market 3, volume 0
    a2 = assess(feats(ret_z=4.5, vol_z=0, vola_z=3, sec_z=4.5, mkt_z=3), CFG)
    expected = 0.30 * 0.75 + 0.20 * 0.5 + 0.20 * 0.75 + 0.10 * 0.5
    assert a2.score == pytest.approx(expected)
    assert a2.score == pytest.approx(0.525)
    assert a2.level == ShockLevel.WATCH
    # confirmation adds exactly w_volume * component
    a3 = assess(feats(ret_z=4.5, vol_z=6, vola_z=3, sec_z=4.5, mkt_z=3), CFG)
    assert a3.score == pytest.approx(0.725)
    assert a3.level == ShockLevel.SHOCK


def test_sector_wide_move_scores_lower_than_stock_specific():
    stock = assess(feats(ret_z=6, vol_z=6, vola_z=6, sec_z=6, mkt_z=6), CFG)
    sector = assess(feats(ret_z=6, vol_z=6, vola_z=6, sec_z=0.0, mkt_z=3), CFG)
    assert sector.score < stock.score
    assert sector.score == pytest.approx(0.30 + 0.20 + 0.20 + 0.0 + 0.05)
    assert sector.components["sector"] == 0.0


def test_negative_volume_z_contributes_zero():
    a = assess(feats(vol_z=-6), CFG)
    assert a.components["volume"] == 0.0
    assert a.score == 0.0
    assert assess(feats(vol_z=6), CFG).components["volume"] == 1.0


def test_none_inputs():
    a = assess(feats(ret_z=None, vol_z=None, vola_z=None, sec_z=None, mkt_z=None), CFG)
    assert a.score == 0.0
    assert a.level == ShockLevel.NONE
    assert all(v == 0.0 for v in a.components.values())


def test_pathological_z_clamps():
    a = assess(feats(ret_z=1e12, vol_z=1e12, vola_z=-1e12, sec_z=1e12, mkt_z=-1e12), CFG)
    assert a.score == pytest.approx(1.0)
    assert 0.0 <= a.score <= 1.0
    assert a.level == ShockLevel.SEVERE
    inf = assess(feats(ret_z=float("inf"), vol_z=float("nan")), CFG)
    assert inf.components["ret"] == 1.0
    assert inf.components["volume"] == 0.0


def test_not_ready_is_none_but_score_kept():
    a = assess(
        feats(ret_z=6, vol_z=6, vola_z=6, sec_z=6, mkt_z=6, status=FeatureStatus.WARMING_UP), CFG
    )
    assert a.ready is False
    assert a.level == ShockLevel.NONE
    assert a.score == pytest.approx(1.0)
    u = assess(feats(status=FeatureStatus.UNAVAILABLE), CFG)
    assert u.ready is False and u.level == ShockLevel.NONE


def test_level_thresholds_boundaries():
    # only ret component: score = 0.30 * min(z/6,1); use custom weights to hit thresholds exactly
    cfg = ShockConfig(weights=ShockWeights(ret=1, volume=0, volatility=0, sector=0, market=0))
    assert assess(feats(ret_z=6 * 0.34), cfg).level == ShockLevel.NONE
    assert assess(feats(ret_z=6 * 0.351), cfg).level == ShockLevel.WATCH
    assert assess(feats(ret_z=6 * 0.551), cfg).level == ShockLevel.SHOCK
    assert assess(feats(ret_z=6 * 0.751), cfg).level == ShockLevel.SEVERE


def test_direction_fallbacks():
    assert (
        assess(feats(sector_residual=0.01, market_residual=-0.01, ret_5m=-0.01), CFG).direction
        == ShockDirection.POSITIVE
    )
    assert (
        assess(feats(sector_residual=None, market_residual=0.02, ret_5m=-0.01), CFG).direction
        == ShockDirection.POSITIVE
    )
    assert (
        assess(feats(sector_residual=None, market_residual=None, ret_5m=-0.03), CFG).direction
        == ShockDirection.NEGATIVE
    )
    assert (
        assess(feats(sector_residual=None, market_residual=None, ret_5m=0.03), CFG).direction
        == ShockDirection.POSITIVE
    )
    assert (
        assess(feats(sector_residual=None, market_residual=None, ret_5m=None), CFG).direction
        is None
    )


def test_weights_normalised():
    # ShockWeights validates sum==1 at construction; assess() must still normalise defensively,
    # so build off-sum weights with model_construct (bypasses the validator).
    # weights summing to 2 behave identically to normalised ones
    w2 = ShockWeights.model_construct(ret=0.6, volume=0.4, volatility=0.4, sector=0.4, market=0.2)
    f = feats(ret_z=4.5, vol_z=0, vola_z=3, sec_z=4.5, mkt_z=3)
    assert assess(f, ShockConfig.model_construct(weights=w2)).score == pytest.approx(
        assess(f, CFG).score
    )
    # all-ones weights -> mean of components
    w1 = ShockWeights.model_construct(ret=1, volume=1, volatility=1, sector=1, market=1)
    all_six = feats(ret_z=6, vol_z=0, vola_z=0, sec_z=0, mkt_z=0)
    assert assess(all_six, ShockConfig.model_construct(weights=w1)).score == pytest.approx(0.2)
    # degenerate all-zero weights -> equal weights, no ZeroDivisionError
    w0 = ShockWeights.model_construct(ret=0, volume=0, volatility=0, sector=0, market=0)
    assert assess(all_six, ShockConfig.model_construct(weights=w0)).score == pytest.approx(0.2)


def test_calibrated_always_false_and_metadata():
    for f in (feats(), feats(ret_z=6, vol_z=6, vola_z=6, sec_z=6, mkt_z=6)):
        a = assess(f, CFG)
        assert a.calibrated is False
        assert a.symbol == "NVDA" and a.as_of == TS
