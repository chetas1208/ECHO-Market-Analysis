"""Async persistence for append-only execution intents and broker evidence."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.execution.types import ExecutionFill, ExecutionState, OrderIntent, ProviderOrder
from app.models.execution import (
    BrokerReconciliationRecord,
    ExecutionEventRecord,
    ExecutionFillRecord,
    OrderIntentRecord,
)


class ExecutionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def by_idempotency(self, key: str) -> OrderIntentRecord | None:
        return await self.session.scalar(
            select(OrderIntentRecord).where(OrderIntentRecord.idempotency_key == key)
        )

    async def list_intents(self) -> list[OrderIntentRecord]:
        result = await self.session.scalars(
            select(OrderIntentRecord).order_by(OrderIntentRecord.created_at.desc())
        )
        return list(result)

    async def events_for(self, intent_ids: list[UUID]) -> dict[UUID, ExecutionEventRecord]:
        if not intent_ids:
            return {}
        result = await self.session.scalars(
            select(ExecutionEventRecord)
            .where(ExecutionEventRecord.order_intent_id.in_(intent_ids))
            .order_by(ExecutionEventRecord.event_timestamp.asc())
        )
        latest: dict[UUID, ExecutionEventRecord] = {}
        for event in result:
            latest[event.order_intent_id] = event
        return latest

    async def add_intent(self, intent: OrderIntent) -> OrderIntentRecord:
        record = OrderIntentRecord(
            id=UUID(intent.id),
            decision_id=intent.decision_id,
            forecast_id=intent.forecast_id,
            strategy_version=intent.strategy_version,
            config_hash=intent.config_hash,
            symbol=intent.symbol,
            side=intent.side,
            quantity=intent.quantity,
            notional=intent.notional,
            order_type=intent.order_type,
            time_in_force=intent.time_in_force,
            limit_price=intent.limit_price,
            stop_metadata=intent.stop_metadata,
            hedge_metadata=intent.hedge_metadata,
            created_at=intent.created_at,
            idempotency_key=intent.idempotency_key,
            execution_source=intent.execution_source,
            state=ExecutionState.CREATED.value,
            content_hash=intent.content_hash,
        )
        self.session.add(record)
        await self.session.flush()
        await self.add_event(record.id, ExecutionState.CREATED.value, {})
        return record

    async def add_event(self, intent_id: UUID, state: str, metadata: dict[str, object]) -> None:
        self.session.add(
            ExecutionEventRecord(
                order_intent_id=intent_id,
                state=state,
                event_timestamp=datetime.now(UTC),
                metadata_=metadata,
            )
        )

    async def add_order_event(
        self, intent: OrderIntent, order: ProviderOrder, state: ExecutionState
    ) -> None:
        await self.add_event(
            UUID(intent.id),
            state.value,
            {
                "external_order_id": order.external_order_id,
                "client_order_id": order.client_order_id,
                "status": order.status.value,
                "filled_quantity": order.filled_quantity,
                "average_fill_price": order.average_fill_price,
            },
        )

    async def add_fills(self, intent: OrderIntent, fills: tuple[ExecutionFill, ...]) -> None:
        for fill in fills:
            self.session.add(
                ExecutionFillRecord(
                    order_intent_id=UUID(intent.id),
                    external_order_id=fill.external_order_id,
                    external_fill_id=fill.external_fill_id,
                    timestamp=fill.timestamp,
                    quantity=fill.quantity,
                    price=fill.price,
                    fees=fill.fees,
                )
            )

    async def add_reconciliation(
        self,
        provider: str,
        state: str,
        discrepancies: list[str],
        account_snapshot: dict[str, object],
    ) -> None:
        self.session.add(
            BrokerReconciliationRecord(
                provider=provider,
                observed_at=datetime.now(UTC),
                state=state,
                discrepancies=discrepancies,
                account_snapshot=account_snapshot,
            )
        )
