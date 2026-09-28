from datetime import UTC, datetime, timedelta

from app.forecasting.simulator import SimulationConfig, SimulationPoint, simulate_trade
from app.market.types import Bar, Interval, ProviderName


def bars(prices: list[float], start: datetime) -> list[Bar]:
    return [
        Bar(
            symbol="NVDA",
            timestamp=start + timedelta(minutes=index),
            interval=Interval.M1,
            open=price,
            high=price * 1.001,
            low=price * 0.999,
            close=price,
            volume=100,
            source=ProviderName.REPLAY,
        )
        for index, price in enumerate(prices)
    ]


def point(q50: float, probability: float) -> SimulationPoint:
    return SimulationPoint(
        horizon="1D",
        target_timestamp=datetime(2026, 9, 20, 10, 3, tzinfo=UTC),
        q10=q50 - 0.01,
        q50=q50,
        q90=q50 + 0.01,
        probability_positive=probability,
        risk=0.01,
    )


def test_long_uses_next_bar_and_includes_costs() -> None:
    decision = datetime(2026, 9, 20, 10, 0, tzinfo=UTC)
    result = simulate_trade(
        symbol="NVDA",
        decision_timestamp=decision,
        point=point(0.03, 0.8),
        bars=bars([50, 50, 52, 52], decision),
        config=SimulationConfig(commission_bps=10),
    )
    assert result.side == "LONG"
    assert result.status == "CLOSED"
    assert result.entry_timestamp == decision + timedelta(minutes=1)
    assert result.net_pnl < result.gross_pnl


def test_short_math_is_positive_when_price_falls() -> None:
    decision = datetime(2026, 9, 20, 10, 0, tzinfo=UTC)
    result = simulate_trade(
        symbol="DAL",
        decision_timestamp=decision,
        point=point(-0.03, 0.2),
        bars=bars([50, 50, 48, 48], decision),
        config=SimulationConfig(commission_bps=0, spread_bps=0, slippage_bps=0),
    )
    assert result.side == "SHORT"
    assert result.status == "CLOSED"
    assert result.gross_pnl > 0
    assert result.net_pnl == result.gross_pnl


def test_low_confidence_forecast_is_a_recorded_no_trade() -> None:
    decision = datetime(2026, 9, 20, 10, 0, tzinfo=UTC)
    result = simulate_trade(
        symbol="NVDA",
        decision_timestamp=decision,
        point=point(0.03, 0.51),
        bars=bars([50, 50, 52, 52], decision),
        config=SimulationConfig(),
    )
    assert result.side == "NO_TRADE"
    assert result.status == "NO_TRADE"
    assert result.reason == "probability_threshold_not_met"


def test_missing_future_entry_cannot_use_the_decision_bar() -> None:
    decision = datetime(2026, 9, 20, 10, 0, tzinfo=UTC)
    result = simulate_trade(
        symbol="NVDA",
        decision_timestamp=decision,
        point=point(0.03, 0.8),
        bars=bars([50], decision),
        config=SimulationConfig(),
    )
    assert result.status == "CANCELLED_BEFORE_ENTRY"
    assert result.entry_timestamp is None
