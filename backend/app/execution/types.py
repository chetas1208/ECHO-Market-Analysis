"""Stable ECHO execution contracts. Broker SDK models never cross this boundary."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal


class ExecutionMode(StrEnum):
    DISABLED = "DISABLED"
    REPLAY = "REPLAY"
    PAPER = "PAPER"
    LIVE = "LIVE"


class ExecutionState(StrEnum):
    CREATED = "CREATED"
    SUBMITTING = "SUBMITTING"
    SUBMITTED = "SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"
    REJECTED_PRE_EXECUTION = "REJECTED_PRE_EXECUTION"


class ExecutionOrderStatus(StrEnum):
    OPEN = "OPEN"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"


Side = Literal["LONG", "SHORT"]


def utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("execution timestamps must be timezone-aware")
    return value.astimezone(UTC)


@dataclass(frozen=True)
class PaperDecision:
    """The only decision shape allowed to reach the execution service."""

    decision_id: str
    state: str
    forecast_id: str
    strategy_version: str
    config_hash: str
    symbol: str
    side: Side
    quantity: float | None = None
    notional: float | None = None
    event_timestamp: datetime | None = None
    market_timestamp: datetime | None = None
    market_fresh: bool = False
    forecast_valid: bool = False
    risk_allowed: bool = False
    kill_switch: bool = False
    daily_loss_limit_ok: bool = True
    max_positions_ok: bool = False
    max_exposure_ok: bool = False
    buying_power: float | None = None
    shortable: bool = True
    stop_metadata: dict[str, Any] = field(default_factory=dict)
    hedge_metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.decision_id.strip() or not self.forecast_id.strip():
            raise ValueError("decision_id and forecast_id are required")
        if not self.strategy_version.strip() or not self.config_hash.strip():
            raise ValueError("strategy version and config hash are required")
        if not self.symbol.strip() or self.symbol.upper() != self.symbol:
            raise ValueError("symbol must be uppercase and non-empty")
        if (self.quantity is None) == (self.notional is None):
            raise ValueError("exactly one of quantity or notional is required")
        if self.quantity is not None and self.quantity <= 0:
            raise ValueError("quantity must be positive")
        if self.notional is not None and self.notional <= 0:
            raise ValueError("notional must be positive")
        if self.event_timestamp is not None:
            utc(self.event_timestamp)
        if self.market_timestamp is not None:
            utc(self.market_timestamp)


@dataclass(frozen=True)
class OrderIntent:
    id: str
    decision_id: str
    forecast_id: str
    strategy_version: str
    config_hash: str
    symbol: str
    side: Side
    quantity: float | None
    notional: float | None
    order_type: Literal["MARKET", "LIMIT"] = "MARKET"
    time_in_force: Literal["DAY", "GTC"] = "DAY"
    limit_price: float | None = None
    stop_metadata: dict[str, Any] = field(default_factory=dict)
    hedge_metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    idempotency_key: str = ""
    execution_source: Literal["REPLAY", "PAPER"] = "REPLAY"

    def __post_init__(self) -> None:
        if self.order_type == "LIMIT" and (self.limit_price is None or self.limit_price <= 0):
            raise ValueError("limit orders require a positive limit_price")
        if self.quantity is not None and self.quantity <= 0:
            raise ValueError("order quantity must be positive")
        if self.notional is not None and self.notional <= 0:
            raise ValueError("order notional must be positive")
        if (self.quantity is None) == (self.notional is None):
            raise ValueError("exactly one order size must be set")
        utc(self.created_at)

    @property
    def client_order_id(self) -> str:
        return f"echo-{self.idempotency_key[:40]}"

    @staticmethod
    def idempotency_key_for(decision: PaperDecision) -> str:
        raw = "|".join(
            [
                decision.decision_id,
                decision.forecast_id,
                decision.strategy_version,
                decision.symbol,
                decision.side,
            ]
        )
        return hashlib.sha256(raw.encode()).hexdigest()

    @property
    def content_hash(self) -> str:
        payload = {
            "id": self.id,
            "decision_id": self.decision_id,
            "forecast_id": self.forecast_id,
            "strategy_version": self.strategy_version,
            "config_hash": self.config_hash,
            "symbol": self.symbol,
            "side": self.side,
            "quantity": self.quantity,
            "notional": self.notional,
            "order_type": self.order_type,
            "time_in_force": self.time_in_force,
            "limit_price": self.limit_price,
            "idempotency_key": self.idempotency_key,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


@dataclass(frozen=True)
class ProviderOrder:
    external_order_id: str
    client_order_id: str
    status: ExecutionOrderStatus
    symbol: str
    side: Side
    quantity: float
    filled_quantity: float = 0.0
    average_fill_price: float | None = None
    submitted_at: datetime | None = None
    raw_status: str | None = None


@dataclass(frozen=True)
class ExecutionFill:
    external_order_id: str
    external_fill_id: str
    timestamp: datetime
    quantity: float
    price: float
    fees: float = 0.0


@dataclass(frozen=True)
class AccountSnapshot:
    status: str
    equity: float | None
    cash: float | None
    buying_power: float | None
    updated_at: datetime


@dataclass(frozen=True)
class PositionSnapshot:
    symbol: str
    side: str
    quantity: float
    average_entry_price: float | None
    current_price: float | None
    unrealized_pnl: float | None


@dataclass(frozen=True)
class ExecutionHealth:
    mode: ExecutionMode
    provider: str
    configured: bool
    healthy: bool
    account_status: str | None
    kill_switch: bool
    data_fresh: bool
    reconciliation_state: str
    message: str | None = None
