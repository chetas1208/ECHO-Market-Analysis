"""Tests for app.market.shock.events (pure, no DB/network)."""

import json
import math
from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.market.shock.events import build_shock_event
from app.market.types import (
    FeatureStatus,
    FeatureValue,
    ProviderName,
    ShockAssessment,
    ShockDirection,
    ShockLevel,
    SymbolFeatures,
)
from app.schemas.event import EventCreate, SourceType, is_valid_event_id

AS_OF = datetime(2026, 9, 18, 14, 35, tzinfo=UTC)


def _fv(v: float | None) -> FeatureValue:
    return FeatureValue(
        value=v, status=FeatureStatus.READY if v is not None else FeatureStatus.UNAVAILABLE
    )


def _features(symbol: str = "NVDA", **kw) -> SymbolFeatures:
    base = {
        "symbol": symbol,
        "as_of": AS_OF,
        "price": 100.0,
        "ret_5m": _fv(-0.045),
        "return_z": _fv(-6.2),
        "volume_z": _fv(8.1),
        "volume_z_method": "tod",
        "volatility_z": _fv(3.3),
        "market_residual": _fv(-0.044),
        "market_residual_z": _fv(-5.0),
        "sector_residual": _fv(-0.043),
        "sector_residual_z": _fv(-4.8),
        "sector_benchmark": "SOXX",
        "market_benchmark": "SPY",
        "overall_status": FeatureStatus.READY,
    }
    base.update(kw)
    return SymbolFeatures(**base)


def _assessment(
    symbol: str = "NVDA",
    direction: ShockDirection | None = ShockDirection.NEGATIVE,
    ready: bool = True,
    **kw,
) -> ShockAssessment:
    base = {
        "symbol": symbol,
        "as_of": AS_OF,
        "score": 0.86,
        "level": ShockLevel.SEVERE,
        "direction": direction,
        "components": {
            "ret": 1.0,
            "volume": 1.0,
            "volatility": 0.8,
            "sector": 0.4,
            "market": 0.2,
        },
        "ready": ready,
    }
    base.update(kw)
    return ShockAssessment(**base)


def test_validates_and_fields() -> None:
    ev = build_shock_event(_assessment(), _features(), ProviderName.MASSIVE)
    assert isinstance(ev, EventCreate)
    EventCreate.model_validate(ev.model_dump(mode="json"))
    assert ev.source_type == SourceType.MARKET
    assert ev.event_type == "market_shock"
    assert ev.companies == ["NVDA"]
    assert ev.economic_channels == {}
    assert ev.severity == pytest.approx(0.86)
    assert ev.novelty == 1.0
    assert ev.timestamp == AS_OF
    assert ev.source_refs == [{"name": "massive"}]
    assert ev.confidence == pytest.approx(0.6)  # 3 of 5 components >= 0.5
    md = ev.metadata
    assert md["confidence_semantics"] == "signal_agreement_not_probability"
    assert md["calibrated"] is False
    assert md["direction"] == "negative"
    assert md["level"] == "severe"
    assert md["shock_score"] == pytest.approx(0.86)
    assert md["volume_z_method"] == "tod"
    assert md["sector_benchmark"] == "SOXX"
    assert md["provider"] == "massive"
    assert md["return_5m"] == pytest.approx(-0.045)
    assert set(md["components"]) == {"ret", "volume", "volatility", "sector", "market"}


def test_summary_factual_no_percent_confidence() -> None:
    ev = build_shock_event(_assessment(), _features(), ProviderName.MASSIVE)
    assert ev.summary is not None
    assert "0.86" in ev.summary
    assert "sigma" in ev.summary
    assert "-6.20" in ev.summary
    assert "confidence" not in ev.summary.lower()
    assert "%" not in ev.summary


def test_deterministic_id() -> None:
    a = build_shock_event(_assessment(), _features(), ProviderName.MASSIVE)
    b = build_shock_event(_assessment(), _features(), ProviderName.MASSIVE)
    assert a.id == b.id == "evt_mkt_nvda_202609181435_neg"
    assert a.id is not None and is_valid_event_id(a.id)
    pos = build_shock_event(
        _assessment(direction=ShockDirection.POSITIVE), _features(), ProviderName.MASSIVE
    )
    assert pos.id == "evt_mkt_nvda_202609181435_pos"


def test_id_sanitises_symbol_and_utc_normalises() -> None:
    est = timezone(timedelta(hours=-5))
    as_of = datetime(2026, 9, 18, 9, 35, tzinfo=est)
    ev = build_shock_event(
        _assessment(symbol="BRK.B", as_of=as_of),
        _features(symbol="BRK.B"),
        ProviderName.ALPACA,
    )
    assert ev.id == "evt_mkt_brk_b_202609181435_neg"
    assert ev.timestamp.utcoffset() == timedelta(0)
    assert ev.timestamp == as_of


def test_json_round_trip() -> None:
    ev = build_shock_event(_assessment(), _features(), ProviderName.MASSIVE)
    dumped = ev.model_dump(mode="json")
    again = json.loads(json.dumps(dumped, allow_nan=False))
    assert again == dumped
    assert EventCreate.model_validate(again).id == ev.id


def test_none_and_nan_metadata_are_json_safe() -> None:
    feats = _features(
        volume_z=_fv(None),
        volume_z_method=None,
        return_z=FeatureValue(value=math.nan, status=FeatureStatus.READY),
        sector_residual=FeatureValue(value=math.inf, status=FeatureStatus.READY),
    )
    ev = build_shock_event(
        _assessment(components={"ret": math.nan, "volume": 0.9}), feats, ProviderName.MASSIVE
    )
    assert ev.metadata["volume_z"] is None
    assert ev.metadata["return_z"] is None
    assert ev.metadata["sector_residual"] is None
    assert ev.metadata["components"]["ret"] is None
    assert ev.confidence == pytest.approx(0.5)
    json.dumps(ev.model_dump(mode="json"), allow_nan=False)
    assert ev.summary is not None and "n/a" in ev.summary and "nan" not in ev.summary.lower()


def test_replay_is_mock_and_others_not() -> None:
    replay = build_shock_event(_assessment(), _features(), ProviderName.REPLAY)
    assert replay.is_mock is True
    assert replay.source_refs == [{"name": "replay"}]
    assert replay.metadata["provider"] == "replay"
    assert replay.summary is not None and "REPLAY" in replay.summary
    assert build_shock_event(_assessment(), _features(), ProviderName.MASSIVE).is_mock is False
    assert build_shock_event(_assessment(), _features(), ProviderName.ALPACA).is_mock is False


def test_titles_by_direction() -> None:
    neg = build_shock_event(_assessment(), _features(), ProviderName.MASSIVE)
    pos = build_shock_event(
        _assessment(direction=ShockDirection.POSITIVE), _features(), ProviderName.MASSIVE
    )
    assert neg.title == "NVDA abnormal downside move"
    assert pos.title == "NVDA abnormal upside move"


def test_confidence_bounds() -> None:
    none_strong = _assessment(components={"a": 0.1, "b": 0.49})
    assert build_shock_event(none_strong, _features(), ProviderName.MASSIVE).confidence == 0.0
    all_strong = _assessment(components={"a": 0.5, "b": 1.0})
    assert build_shock_event(all_strong, _features(), ProviderName.MASSIVE).confidence == 1.0
    empty = _assessment(components={})
    assert build_shock_event(empty, _features(), ProviderName.MASSIVE).confidence == 0.0


def test_no_direction_raises() -> None:
    with pytest.raises(ValueError, match="direction"):
        build_shock_event(_assessment(direction=None), _features(), ProviderName.MASSIVE)


def test_not_ready_raises() -> None:
    with pytest.raises(ValueError, match="ready"):
        build_shock_event(_assessment(ready=False), _features(), ProviderName.MASSIVE)


def test_naive_as_of_and_symbol_mismatch_raise() -> None:
    with pytest.raises(ValueError, match="timezone"):
        build_shock_event(
            _assessment(as_of=datetime(2026, 9, 18, 14, 35)), _features(), ProviderName.MASSIVE
        )
    with pytest.raises(ValueError, match="mismatch"):
        build_shock_event(_assessment(), _features(symbol="AMD"), ProviderName.MASSIVE)
