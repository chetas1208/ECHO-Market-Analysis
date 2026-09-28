from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.execution.providers import AlpacaPaperExecutionProvider, ProviderError
from app.execution.service import ExecutionRejected, ExecutionService
from app.execution.settings import ExecutionSettings
from app.execution.types import ExecutionState, PaperDecision
from app.strategy.consistency import validate_conviction_consistency


def decision(**overrides: object) -> PaperDecision:
    values: dict[str, object] = {
        "decision_id": "decision-1",
        "state": "PAPER_TRADE",
        "forecast_id": "forecast-1",
        "strategy_version": "echo-rp-v1",
        "config_hash": "a" * 64,
        "symbol": "NVDA",
        "side": "LONG",
        "quantity": 2.0,
        "market_fresh": True,
        "forecast_valid": True,
        "risk_allowed": True,
        "max_positions_ok": True,
        "max_exposure_ok": True,
        "event_timestamp": datetime.now(UTC),
        "market_timestamp": datetime.now(UTC),
    }
    values.update(overrides)
    return PaperDecision(**values)


def test_replay_dry_run_and_idempotency() -> None:
    service = ExecutionService(ExecutionSettings(_env_file=None, execution_mode="REPLAY"))
    intent, order, state = service.execute(decision(), dry_run=True)
    assert order is None and state == ExecutionState.CREATED
    repeated, order, repeated_state = service.execute(decision(), dry_run=False)
    assert repeated.id == intent.id
    assert order is not None and repeated_state == ExecutionState.FILLED
    again, duplicate, duplicate_state = service.execute(decision(), dry_run=False)
    assert again.id == repeated.id
    assert duplicate is not None and duplicate.external_order_id == order.external_order_id
    assert duplicate_state == ExecutionState.FILLED
    assert len(service.list_orders()) == 1


def test_gate_blocks_non_paper_trade_and_stale_data() -> None:
    service = ExecutionService(ExecutionSettings(_env_file=None, execution_mode="REPLAY"))
    with pytest.raises(ExecutionRejected) as rejected:
        service.execute(decision(state="WATCH"), dry_run=False)
    assert "DECISION_NOT_PAPER_TRADE" in rejected.value.reasons
    with pytest.raises(ExecutionRejected) as rejected:
        service.execute(decision(decision_id="decision-2", market_fresh=False), dry_run=False)
    assert "STALE_MARKET_DATA" in rejected.value.reasons


def test_kill_switch_blocks_without_provider_call() -> None:
    service = ExecutionService(
        ExecutionSettings(_env_file=None, execution_mode="REPLAY", execution_kill_switch=True)
    )
    with pytest.raises(ExecutionRejected) as rejected:
        service.execute(decision(), dry_run=False)
    assert "KILL_SWITCH_ACTIVE" in rejected.value.reasons


def test_buying_power_is_an_execution_gate() -> None:
    service = ExecutionService(ExecutionSettings(_env_file=None, execution_mode="REPLAY"))
    with pytest.raises(ExecutionRejected) as rejected:
        service.execute(decision(quantity=None, notional=500.0, buying_power=100.0), dry_run=False)
    assert "BUYING_POWER" in rejected.value.reasons


def test_live_mode_is_rejected_and_alpaca_requires_paper() -> None:
    with pytest.raises(ValueError, match="LIVE"):
        ExecutionSettings(_env_file=None, execution_mode="LIVE")
    with pytest.raises(ProviderError, match="live"):
        AlpacaPaperExecutionProvider("key", "secret", paper=False)


def test_missing_alpaca_credentials_are_unconfigured() -> None:
    provider = AlpacaPaperExecutionProvider(None, None, paper=True)
    assert provider.configured is False
    assert provider.health()[0] is False


def test_conviction_artifacts_match_frozen_config() -> None:
    root = Path(__file__).resolve().parents[3]
    missing = validate_conviction_consistency(
        root / "configs/strategies/echo-rp-v1.yaml",
        root / "artifacts/strategy/conviction-final.md",
        root / "artifacts/strategy/conviction-prompt.txt",
    )
    assert missing == []
