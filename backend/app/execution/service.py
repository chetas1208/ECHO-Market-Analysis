"""Safety gate and idempotent execution orchestration."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from app.execution.providers import (
    AlpacaPaperExecutionProvider,
    ProviderError,
    ReplayExecutionProvider,
)
from app.execution.settings import ExecutionSettings
from app.execution.types import (
    AccountSnapshot,
    ExecutionHealth,
    ExecutionMode,
    ExecutionOrderStatus,
    ExecutionState,
    OrderIntent,
    PaperDecision,
    PositionSnapshot,
    ProviderOrder,
)
from app.market.universe import get_universe


class ExecutionRejected(ValueError):
    """A deterministic pre-submit rejection; no broker call was made."""

    def __init__(self, reasons: tuple[str, ...]) -> None:
        self.reasons = reasons
        super().__init__(";".join(reasons))


class ExecutionService:
    def __init__(self, settings: ExecutionSettings) -> None:
        self.settings = settings
        self.mode = ExecutionMode(settings.execution_mode)
        self._provider = self._build_provider()
        self._intents: dict[str, OrderIntent] = {}
        self._orders: dict[str, ProviderOrder] = {}
        self._states: dict[str, ExecutionState] = {}
        self._reconciliation_state = "UNKNOWN"

    def _build_provider(self):
        if self.mode == ExecutionMode.REPLAY:
            return ReplayExecutionProvider()
        if self.mode == ExecutionMode.PAPER:
            return AlpacaPaperExecutionProvider(
                self.settings.alpaca_api_key.get_secret_value()
                if self.settings.alpaca_api_key
                else None,
                self.settings.alpaca_api_secret.get_secret_value()
                if self.settings.alpaca_api_secret
                else None,
                paper=self.settings.alpaca_paper,
            )
        return None

    @property
    def provider_name(self) -> str:
        return self._provider.name if self._provider else "disabled"

    def health(self, *, data_fresh: bool = False) -> ExecutionHealth:
        configured = self._provider is not None and getattr(self._provider, "configured", True)
        healthy = False
        message = "execution disabled"
        account_status = None
        if self._provider is not None:
            healthy, message = self._provider.health()
            if healthy and self.mode == ExecutionMode.PAPER:
                try:
                    account_status = self._provider.get_account().status
                except ProviderError:
                    healthy = False
        return ExecutionHealth(
            self.mode,
            self.provider_name,
            configured,
            healthy,
            account_status,
            self.settings.execution_kill_switch,
            data_fresh,
            self._reconciliation_state,
            message,
        )

    def create_intent(self, decision: PaperDecision, *, now: datetime | None = None) -> OrderIntent:
        reasons = self._validate(decision)
        key = OrderIntent.idempotency_key_for(decision)
        existing = self._intents.get(key)
        if existing is not None:
            return existing
        if reasons:
            raise ExecutionRejected(tuple(reasons))
        intent = OrderIntent(
            id=str(uuid.uuid4()),
            decision_id=decision.decision_id,
            forecast_id=decision.forecast_id,
            strategy_version=decision.strategy_version,
            config_hash=decision.config_hash,
            symbol=decision.symbol,
            side=decision.side,
            quantity=self._round_quantity(decision.quantity),
            notional=decision.notional,
            stop_metadata=decision.stop_metadata,
            hedge_metadata=decision.hedge_metadata,
            created_at=now or datetime.now(UTC),
            idempotency_key=key,
            execution_source="PAPER" if self.mode == ExecutionMode.PAPER else "REPLAY",
        )
        self._intents[key] = intent
        self._states[key] = ExecutionState.CREATED
        return intent

    def execute(
        self, decision: PaperDecision, *, dry_run: bool = False
    ) -> tuple[OrderIntent, ProviderOrder | None, ExecutionState]:
        intent = self.create_intent(decision)
        if dry_run:
            return intent, None, ExecutionState.CREATED
        existing = self._orders.get(intent.idempotency_key)
        if existing is not None:
            return intent, existing, self._state_for(existing)
        if self._provider is None:
            self._states[intent.idempotency_key] = ExecutionState.FAILED
            return intent, None, ExecutionState.FAILED
        self._states[intent.idempotency_key] = ExecutionState.SUBMITTING
        try:
            order = self._provider.submit_order(intent)
        except ProviderError:
            self._states[intent.idempotency_key] = ExecutionState.FAILED
            raise
        self._orders[intent.idempotency_key] = order
        state = self._state_for(order)
        self._states[intent.idempotency_key] = state
        return intent, order, state

    def list_orders(self) -> list[ProviderOrder]:
        return list(self._orders.values())

    def account(self) -> AccountSnapshot | None:
        return self._provider.get_account() if self._provider else None

    def positions(self) -> list[PositionSnapshot]:
        return self._provider.get_positions() if self._provider else []

    def reconcile(self) -> dict[str, Any]:
        if self._provider is None:
            self._reconciliation_state = "DISABLED"
            return {"state": self._reconciliation_state, "discrepancies": []}
        broker_orders = {order.external_order_id for order in self._provider.list_open_orders()}
        local_orders = {
            order.external_order_id
            for order in self._orders.values()
            if order.status == ExecutionOrderStatus.OPEN
        }
        discrepancies = sorted(broker_orders ^ local_orders)
        self._reconciliation_state = "DEGRADED" if discrepancies else "OK"
        return {"state": self._reconciliation_state, "discrepancies": discrepancies}

    def _validate(self, decision: PaperDecision) -> list[str]:
        reasons: list[str] = []
        if self.mode not in {ExecutionMode.PAPER, ExecutionMode.REPLAY}:
            reasons.append("EXECUTION_DISABLED")
        if decision.state != "PAPER_TRADE":
            reasons.append("DECISION_NOT_PAPER_TRADE")
        allowed = self.settings.symbols() or frozenset(get_universe().equities())
        if decision.symbol not in allowed:
            reasons.append("SYMBOL_NOT_ALLOWED")
        if not decision.market_fresh:
            reasons.append("STALE_MARKET_DATA")
        if not decision.forecast_valid:
            reasons.append("FORECAST_INVALID")
        if not decision.risk_allowed:
            reasons.append("RISK_REJECTED")
        if decision.kill_switch or self.settings.execution_kill_switch:
            reasons.append("KILL_SWITCH_ACTIVE")
        if not decision.daily_loss_limit_ok:
            reasons.append("DAILY_LOSS_LIMIT")
        if not decision.max_positions_ok:
            reasons.append("MAX_POSITIONS")
        if not decision.max_exposure_ok:
            reasons.append("MAX_EXPOSURE")
        if (
            decision.notional is not None
            and decision.buying_power is not None
            and decision.notional > decision.buying_power
        ):
            reasons.append("BUYING_POWER")
        if decision.side == "SHORT" and not decision.shortable:
            reasons.append("ASSET_NOT_SHORTABLE")
        if self._provider is not None:
            valid, reason = self._provider.validate_asset(decision.symbol, decision.side)
            if not valid and reason:
                reasons.append(reason.upper())
        return reasons

    @staticmethod
    def _round_quantity(quantity: float | None) -> float | None:
        if quantity is None:
            return None
        rounded = round(quantity, 6)
        if rounded <= 0:
            raise ExecutionRejected(("ZERO_QUANTITY",))
        return rounded

    @staticmethod
    def _state_for(order: ProviderOrder) -> ExecutionState:
        return {
            ExecutionOrderStatus.OPEN: ExecutionState.SUBMITTED,
            ExecutionOrderStatus.FILLED: ExecutionState.FILLED,
            ExecutionOrderStatus.CANCELLED: ExecutionState.CANCELLED,
            ExecutionOrderStatus.REJECTED: ExecutionState.REJECTED,
            ExecutionOrderStatus.EXPIRED: ExecutionState.EXPIRED,
        }.get(order.status, ExecutionState.FAILED)
