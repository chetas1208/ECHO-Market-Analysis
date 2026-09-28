from datetime import UTC, datetime, timedelta

import pytest

from app.forecasting.features import FeatureLeakageError, build_feature_vector
from app.forecasting.targets import build_car_targets
from app.market.types import Bar, Interval, ProviderName


def _bars(symbol: str, start: datetime, values: list[float]) -> list[Bar]:
    return [
        Bar(
            symbol=symbol,
            timestamp=start + timedelta(days=index),
            interval=Interval.M1,
            open=value,
            high=value,
            low=value,
            close=value,
            volume=100,
            source=ProviderName.REPLAY,
        )
        for index, value in enumerate(values)
    ]


def test_car_targets_skip_weekends_and_use_trading_sessions() -> None:
    start = datetime(2025, 1, 3, 15, 0, tzinfo=UTC)  # Friday
    asset = _bars("NVDA", start, [100, 101, 102, 103, 104, 105])
    market = _bars("SPY", start, [100, 100, 100, 100, 100, 100])
    sector = _bars("SOXX", start, [100, 100, 100, 100, 100, 100])
    targets = build_car_targets(
        asset_bars=asset,
        market_bars=market,
        sector_bars=sector,
        issuance_timestamp=start,
        data_cutoff_at=start,
        beta_market=0.0,
        beta_sector=0.0,
    )
    assert (
        targets["1D"].target_timestamp.astimezone(UTC).date()
        == datetime(2025, 1, 6, tzinfo=UTC).date()
    )
    assert targets["1D"].cumulative_abnormal_return > 0


def test_target_builder_uses_future_bars_only_for_training_targets() -> None:
    start = datetime(2025, 1, 2, 15, 0, tzinfo=UTC)
    targets = build_car_targets(
        asset_bars=_bars("NVDA", start, [100, 101]),
        market_bars=_bars("SPY", start, [100, 100]),
        sector_bars=_bars("SOXX", start, [100, 100]),
        issuance_timestamp=start,
        data_cutoff_at=start,
        beta_market=1.0,
        beta_sector=1.0,
    )
    assert "1D" in targets


def test_feature_builder_rejects_future_bars() -> None:
    start = datetime(2025, 1, 2, 15, 0, tzinfo=UTC)
    with pytest.raises(FeatureLeakageError, match="future market bar"):
        build_feature_vector(
            event={"timestamp": start, "economic_channels": {}},
            symbol="NVDA",
            issuance_timestamp=start,
            data_cutoff_at=start,
            asset_bars=_bars("NVDA", start, [100, 101]),
            market_bars=_bars("SPY", start, [100]),
            sector_bars=_bars("SOXX", start, [100]),
        )


def test_missing_future_data_is_not_filled() -> None:
    start = datetime(2025, 1, 2, 15, 0, tzinfo=UTC)
    targets = build_car_targets(
        asset_bars=_bars("NVDA", start, [100]),
        market_bars=_bars("SPY", start, [100]),
        sector_bars=_bars("SOXX", start, [100]),
        issuance_timestamp=start,
        data_cutoff_at=start,
        beta_market=1.0,
        beta_sector=1.0,
    )
    assert targets == {}
