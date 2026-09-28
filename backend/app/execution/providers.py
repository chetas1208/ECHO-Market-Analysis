"""Execution adapters. Alpaca SDK types are normalized before leaving this file."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from app.execution.types import (
    AccountSnapshot,
    ExecutionFill,
    ExecutionMode,
    ExecutionOrderStatus,
    OrderIntent,
    PositionSnapshot,
    ProviderOrder,
)


class ProviderError(RuntimeError):
    """A broker/provider failure that must not be retried blindly."""


class ReplayExecutionProvider:
    """Deterministic fake provider for dry-run and parity tests; never a live broker."""

    name = "replay"
    mode = ExecutionMode.REPLAY

    def __init__(self) -> None:
        self._orders: dict[str, ProviderOrder] = {}
        self._fills: dict[str, tuple[ExecutionFill, ...]] = {}

    def health(self) -> tuple[bool, str]:
        return True, "replay provider ready"

    def submit_order(self, intent: OrderIntent) -> ProviderOrder:
        existing = self._orders.get(intent.client_order_id)
        if existing is not None:
            return existing
        quantity = intent.quantity or intent.notional or 0.0
        price = intent.limit_price or 100.0
        order_id = f"replay-{uuid.uuid5(uuid.NAMESPACE_URL, intent.client_order_id)}"
        fill = ExecutionFill(order_id, f"fill-{order_id}", datetime.now(UTC), quantity, price)
        order = ProviderOrder(
            order_id,
            intent.client_order_id,
            ExecutionOrderStatus.FILLED,
            intent.symbol,
            intent.side,
            quantity,
            quantity,
            price,
            fill.timestamp,
            "filled",
        )
        self._orders[intent.client_order_id] = order
        self._fills[order_id] = (fill,)
        return order

    def cancel_order(self, external_order_id: str) -> ProviderOrder:
        for key, order in self._orders.items():
            if order.external_order_id == external_order_id:
                cancelled = ProviderOrder(
                    order.external_order_id,
                    order.client_order_id,
                    ExecutionOrderStatus.CANCELLED,
                    order.symbol,
                    order.side,
                    order.quantity,
                    order.filled_quantity,
                    order.average_fill_price,
                    order.submitted_at,
                    "cancelled",
                )
                self._orders[key] = cancelled
                return cancelled
        raise ProviderError("replay order not found")

    def get_order(self, external_order_id: str) -> ProviderOrder:
        for order in self._orders.values():
            if order.external_order_id == external_order_id:
                return order
        raise ProviderError("replay order not found")

    def list_open_orders(self) -> list[ProviderOrder]:
        return [
            order for order in self._orders.values() if order.status == ExecutionOrderStatus.OPEN
        ]

    def get_positions(self) -> list[PositionSnapshot]:
        return []

    def get_account(self) -> AccountSnapshot:
        now = datetime.now(UTC)
        return AccountSnapshot("ACTIVE", 100_000.0, 100_000.0, 100_000.0, now)

    def get_fills(self, external_order_id: str) -> tuple[ExecutionFill, ...]:
        return self._fills.get(external_order_id, ())

    def validate_asset(self, symbol: str, side: str) -> tuple[bool, str | None]:
        return True, None


class AlpacaPaperExecutionProvider:
    """Alpaca paper adapter; construction and submission refuse live mode."""

    name = "alpaca"
    mode = ExecutionMode.PAPER

    def __init__(
        self, api_key: str | None, api_secret: str | None, *, paper: bool = True, client: Any = None
    ) -> None:
        if paper is not True:
            raise ProviderError("Alpaca live execution is disabled by ECHO")
        self._configured = bool(api_key and api_secret)
        self._client = client
        if self._configured and self._client is None:
            from alpaca.trading.client import TradingClient

            self._client = TradingClient(api_key, api_secret, paper=True)

    @property
    def configured(self) -> bool:
        return self._configured

    def health(self) -> tuple[bool, str]:
        if not self._configured or self._client is None:
            return False, "Alpaca credentials are not configured"
        try:
            account = self._client.get_account()
            return True, str(getattr(account, "status", "connected"))
        except Exception as exc:
            return False, f"Alpaca account unavailable: {type(exc).__name__}"

    def submit_order(self, intent: OrderIntent) -> ProviderOrder:
        if not self._configured or self._client is None:
            raise ProviderError("Alpaca credentials are not configured")
        from alpaca.trading.enums import OrderSide, OrderType, TimeInForce
        from alpaca.trading.requests import LimitOrderRequest, MarketOrderRequest

        side = OrderSide.BUY if intent.side == "LONG" else OrderSide.SELL
        kwargs = {
            "symbol": intent.symbol,
            "side": side,
            "time_in_force": TimeInForce.DAY,
            "client_order_id": intent.client_order_id,
        }
        if intent.quantity is not None:
            kwargs["qty"] = intent.quantity
        else:
            kwargs["notional"] = intent.notional
        request = (
            MarketOrderRequest(type=OrderType.MARKET, **kwargs)
            if intent.order_type == "MARKET"
            else LimitOrderRequest(type=OrderType.LIMIT, limit_price=intent.limit_price, **kwargs)
        )
        try:
            return self._normalize_order(self._client.submit_order(request))
        except Exception as exc:
            raise ProviderError(f"Alpaca submit failed: {type(exc).__name__}") from exc

    def cancel_order(self, external_order_id: str) -> ProviderOrder:
        if self._client is None:
            raise ProviderError("Alpaca is not configured")
        self._client.cancel_order_by_id(external_order_id)
        return self.get_order(external_order_id)

    def get_order(self, external_order_id: str) -> ProviderOrder:
        if self._client is None:
            raise ProviderError("Alpaca is not configured")
        return self._normalize_order(self._client.get_order_by_id(external_order_id))

    def list_open_orders(self) -> list[ProviderOrder]:
        if self._client is None:
            return []
        return [self._normalize_order(order) for order in self._client.get_orders()]

    def get_positions(self) -> list[PositionSnapshot]:
        if self._client is None:
            return []
        return [
            PositionSnapshot(
                str(item.symbol),
                str(item.side),
                float(item.qty),
                self._number(item.avg_entry_price),
                self._number(item.current_price),
                self._number(item.unrealized_pl),
            )
            for item in self._client.get_all_positions()
        ]

    def get_account(self) -> AccountSnapshot:
        if self._client is None:
            raise ProviderError("Alpaca is not configured")
        account = self._client.get_account()
        return AccountSnapshot(
            str(getattr(account, "status", "UNKNOWN")),
            self._number(getattr(account, "equity", None)),
            self._number(getattr(account, "cash", None)),
            self._number(getattr(account, "buying_power", None)),
            datetime.now(UTC),
        )

    def get_fills(self, external_order_id: str) -> tuple[ExecutionFill, ...]:
        order = self.get_order(external_order_id)
        if order.filled_quantity <= 0 or order.average_fill_price is None:
            return ()
        return (
            ExecutionFill(
                order.external_order_id,
                f"fill-{order.external_order_id}",
                order.submitted_at or datetime.now(UTC),
                order.filled_quantity,
                order.average_fill_price,
            ),
        )

    def validate_asset(self, symbol: str, side: str) -> tuple[bool, str | None]:
        if self._client is None:
            return False, "Alpaca is not configured"
        try:
            asset = self._client.get_asset(symbol)
            if not bool(getattr(asset, "tradable", False)):
                return False, "asset_not_tradable"
            if side == "SHORT" and not bool(getattr(asset, "shortable", False)):
                return False, "asset_not_shortable"
            return True, None
        except Exception as exc:
            return False, f"asset_validation_failed:{type(exc).__name__}"

    @staticmethod
    def _number(value: Any) -> float | None:
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @classmethod
    def _normalize_order(cls, value: Any) -> ProviderOrder:
        status = str(getattr(value, "status", "unknown")).lower()
        status_map = {
            "new": ExecutionOrderStatus.OPEN,
            "accepted": ExecutionOrderStatus.OPEN,
            "pending_new": ExecutionOrderStatus.OPEN,
            "partially_filled": ExecutionOrderStatus.OPEN,
            "filled": ExecutionOrderStatus.FILLED,
            "canceled": ExecutionOrderStatus.CANCELLED,
            "rejected": ExecutionOrderStatus.REJECTED,
            "expired": ExecutionOrderStatus.EXPIRED,
        }
        side = "LONG" if str(getattr(value, "side", "buy")).lower().endswith("buy") else "SHORT"
        return ProviderOrder(
            str(value.id),
            str(getattr(value, "client_order_id", "")),
            status_map.get(status, ExecutionOrderStatus.UNKNOWN),
            str(getattr(value, "symbol", "")).upper(),
            side,
            cls._number(getattr(value, "qty", None)) or 0.0,
            cls._number(getattr(value, "filled_qty", None)) or 0.0,
            cls._number(getattr(value, "filled_avg_price", None)),
            getattr(value, "submitted_at", None),
            status,
        )
