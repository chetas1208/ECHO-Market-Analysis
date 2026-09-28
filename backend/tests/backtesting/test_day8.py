from datetime import UTC, datetime, timedelta

import pytest

from app.backtesting.artifacts import write_artifacts
from app.backtesting.clock import ReplayClock, ReplayOrder, ReplayTimestamp
from app.backtesting.datasets import chronological_case_split, fixture_cases
from app.backtesting.engine import BacktestEngine
from app.strategy.policy import (
    ConfirmationMode,
    StrategyAction,
    StrategyConfig,
    StrategyInput,
    decide,
)


def _signal(**overrides: object) -> StrategyInput:
    values: dict[str, object] = {
        "symbol": "NVDA",
        "event_class": "EARNINGS",
        "event_confidence": 0.9,
        "graph_exposure": 0.7,
        "graph_confidence": 0.8,
        "cause_score": 0.8,
        "cause_direction": 1.0,
        "observed_residual": 0.001,
        "residual_z": 0.3,
        "sector_residual_z": 0.2,
        "volume_z": 1.5,
        "response_state": "CONFIRMED",
        "q10": -0.01,
        "q50": 0.02,
        "q90": 0.03,
        "probability_positive": 0.8,
        "horizon_days": 1,
    }
    values.update(overrides)
    return StrategyInput(**values)


def test_policy_emits_long_short_and_abstain_reason() -> None:
    assert decide(_signal()).action == StrategyAction.LONG
    assert (
        decide(
            _signal(
                q50=-0.02,
                probability_positive=0.2,
                cause_direction=-1.0,
                residual_z=-0.3,
                sector_residual_z=-0.2,
            )
        ).action
        == StrategyAction.SHORT
    )
    decision = decide(_signal(residual_z=3.0))
    assert decision.action == StrategyAction.ABSTAIN
    assert "ALREADY_PRICED" in decision.reason_codes


def test_policy_rejects_ood_and_missing_inputs() -> None:
    assert "OOD" in decide(_signal(ood=True)).reason_codes
    assert "MISSING_INPUT" in decide(_signal(q50=None)).reason_codes


def test_replay_clock_orders_equal_timestamps_and_rejects_future() -> None:
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    ordered = ReplayClock.ordered(
        [
            ReplayTimestamp(timestamp, ReplayOrder.EXECUTION),
            ReplayTimestamp(timestamp, ReplayOrder.EVENT_ARRIVAL),
        ]
    )
    assert ordered[0].order == ReplayOrder.EVENT_ARRIVAL
    with pytest.raises(ValueError, match="future"):
        ReplayClock(timestamp).require_available(timestamp + timedelta(seconds=1))


def test_backtest_is_deterministic_and_marks_small_sample() -> None:
    cases = fixture_cases()
    first = BacktestEngine().run(cases)
    second = BacktestEngine().run(cases)
    assert first.run_id == second.run_id
    assert first.dataset_hash == second.dataset_hash
    assert first.metrics.status == "INSUFFICIENT_DATA"
    assert first.metrics.sharpe is None
    assert any(trade.side == "SHORT" for trade in first.trades)


def test_split_is_chronological_and_event_group_safe() -> None:
    split = chronological_case_split(fixture_cases())
    assert split.train and split.validation and split.test
    assert {case.event_group for case in split.train}.isdisjoint(
        {case.event_group for case in split.validation}
    )
    assert split.diagnostics["chronological"] is True


def test_artifacts_are_not_overwritten(tmp_path) -> None:
    result = BacktestEngine(StrategyConfig(confirmation=ConfirmationMode.NONE)).run(fixture_cases())
    target = write_artifacts(result, tmp_path)
    assert {path.name for path in target.iterdir()} == {
        "config.json",
        "metrics.json",
        "equity.csv",
        "drawdown.csv",
        "trades.csv",
        "metadata.json",
        "report.md",
    }
    with pytest.raises(FileExistsError):
        write_artifacts(result, tmp_path)
