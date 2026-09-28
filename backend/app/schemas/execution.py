"""Paper execution API contracts; no raw broker request is exposed."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class PaperExecuteIn(BaseModel):
    state: Literal["PAPER_TRADE"]
    forecast_id: str = Field(min_length=1)
    strategy_version: str = Field(min_length=1)
    config_hash: str = Field(min_length=16)
    symbol: str = Field(min_length=1, max_length=16)
    side: Literal["LONG", "SHORT"]
    quantity: float | None = Field(default=None, gt=0)
    notional: float | None = Field(default=None, gt=0)
    market_fresh: bool = False
    forecast_valid: bool = False
    risk_allowed: bool = False
    kill_switch: bool = False
    daily_loss_limit_ok: bool = True
    max_positions_ok: bool = False
    max_exposure_ok: bool = False
    buying_power: float | None = Field(default=None, gt=0)
    shortable: bool = True
    dry_run: bool = True
    stop_metadata: dict[str, Any] = Field(default_factory=dict)
    hedge_metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _one_size(self) -> "PaperExecuteIn":
        if (self.quantity is None) == (self.notional is None):
            raise ValueError("exactly one of quantity or notional is required")
        return self


class ExecutionOrderOut(BaseModel):
    external_order_id: str
    client_order_id: str
    status: str
    symbol: str
    side: str
    quantity: float
    filled_quantity: float
    average_fill_price: float | None


class ExecutionResponse(BaseModel):
    accepted: bool
    state: str
    intent_id: str | None
    idempotency_key: str | None
    rejection_reasons: list[str] = Field(default_factory=list)
    order: ExecutionOrderOut | None = None
    dry_run: bool


class ExecutionStatusOut(BaseModel):
    mode: str
    provider: str
    configured: bool
    healthy: bool
    account_status: str | None
    kill_switch: bool
    data_fresh: bool
    reconciliation_state: str
    message: str | None


class PaperAccountOut(BaseModel):
    status: str
    equity: float | None
    cash: float | None
    buying_power: float | None
    updated_at: datetime


class PaperPositionOut(BaseModel):
    symbol: str
    side: str
    quantity: float
    average_entry_price: float | None
    current_price: float | None
    unrealized_pnl: float | None
