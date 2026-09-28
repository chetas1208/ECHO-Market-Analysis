"""Paper-only execution and reconciliation status API."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request

from app.api.deps import SessionDep
from app.execution.service import ExecutionRejected, ExecutionService
from app.execution.types import OrderIntent, PaperDecision
from app.repositories.execution import ExecutionRepository
from app.schemas.execution import (
    ExecutionOrderOut,
    ExecutionResponse,
    ExecutionStatusOut,
    PaperAccountOut,
    PaperExecuteIn,
    PaperPositionOut,
)

router = APIRouter(tags=["execution"])


def _service(request: Request) -> ExecutionService:
    return request.app.state.execution_service


@router.get("/execution/status", response_model=ExecutionStatusOut)
async def execution_status(request: Request) -> ExecutionStatusOut:
    value = _service(request).health(data_fresh=False)
    return ExecutionStatusOut(**value.__dict__)


@router.get("/paper/account", response_model=PaperAccountOut | None)
async def paper_account(request: Request) -> PaperAccountOut | None:
    value = _service(request).account()
    return PaperAccountOut(**value.__dict__) if value else None


@router.get("/paper/positions", response_model=list[PaperPositionOut])
async def paper_positions(request: Request) -> list[PaperPositionOut]:
    return [PaperPositionOut(**value.__dict__) for value in _service(request).positions()]


@router.get("/paper/orders", response_model=list[ExecutionOrderOut])
async def paper_orders(request: Request, session: SessionDep) -> list[ExecutionOrderOut]:
    service = _service(request)
    output = [ExecutionOrderOut(**value.__dict__) for value in service.list_orders()]
    repository = ExecutionRepository(session)
    records = await repository.list_intents()
    events = await repository.events_for([record.id for record in records])
    known = {item.client_order_id for item in output}
    for record in records:
        client_order_id = f"echo-{record.idempotency_key[:40]}"
        if client_order_id in known:
            continue
        event = events.get(record.id)
        metadata = event.metadata_ if event else {}
        output.append(
            ExecutionOrderOut(
                external_order_id=str(metadata.get("external_order_id", f"intent-{record.id}")),
                client_order_id=client_order_id,
                status=str(metadata.get("status", record.state)).upper(),
                symbol=record.symbol,
                side=record.side,
                quantity=float(record.quantity or 0),
                filled_quantity=float(metadata.get("filled_quantity", 0) or 0),
                average_fill_price=metadata.get("average_fill_price"),
            )
        )
    return output


@router.post("/paper/execute/{decision_id}", response_model=ExecutionResponse)
async def execute_paper(
    decision_id: str, payload: PaperExecuteIn, request: Request, session: SessionDep
) -> ExecutionResponse:
    if decision_id != decision_id.strip() or not decision_id:
        raise HTTPException(status_code=400, detail="decision_id is required")
    service = _service(request)
    try:
        decision = PaperDecision(
            decision_id=decision_id,
            state=payload.state,
            forecast_id=payload.forecast_id,
            strategy_version=payload.strategy_version,
            config_hash=payload.config_hash,
            symbol=payload.symbol.strip().upper(),
            side=payload.side,
            quantity=payload.quantity,
            notional=payload.notional,
            market_fresh=payload.market_fresh,
            forecast_valid=payload.forecast_valid,
            risk_allowed=payload.risk_allowed,
            kill_switch=payload.kill_switch,
            daily_loss_limit_ok=payload.daily_loss_limit_ok,
            max_positions_ok=payload.max_positions_ok,
            max_exposure_ok=payload.max_exposure_ok,
            buying_power=payload.buying_power,
            shortable=payload.shortable,
            stop_metadata=payload.stop_metadata,
            hedge_metadata=payload.hedge_metadata,
        )
        key = OrderIntent.idempotency_key_for(decision)
        existing = await ExecutionRepository(session).by_idempotency(key)
        if existing is not None:
            return ExecutionResponse(
                accepted=True,
                state=existing.state,
                intent_id=str(existing.id),
                idempotency_key=existing.idempotency_key,
                order=None,
                dry_run=payload.dry_run,
            )
        intent, order, state = service.execute(decision, dry_run=payload.dry_run)
        repository = ExecutionRepository(session)
        await repository.add_intent(intent)
        if order is not None:
            await repository.add_order_event(intent, order, state)
            provider = getattr(service, "_provider", None)
            if provider is not None and hasattr(provider, "get_fills"):
                await repository.add_fills(intent, provider.get_fills(order.external_order_id))
        await session.commit()
    except ExecutionRejected as exc:
        return ExecutionResponse(
            accepted=False,
            state="REJECTED_PRE_EXECUTION",
            intent_id=None,
            idempotency_key=None,
            rejection_reasons=list(exc.reasons),
            dry_run=payload.dry_run,
        )
    return ExecutionResponse(
        accepted=True,
        state=state.value,
        intent_id=intent.id,
        idempotency_key=intent.idempotency_key,
        order=ExecutionOrderOut(**order.__dict__) if order else None,
        dry_run=payload.dry_run,
    )


@router.post("/execution/reconcile")
async def reconcile_execution(request: Request, session: SessionDep) -> dict[str, object]:
    service = _service(request)
    result = service.reconcile()
    account = service.account()
    await ExecutionRepository(session).add_reconciliation(
        service.provider_name,
        str(result["state"]),
        list(result["discrepancies"]),
        json.loads(json.dumps(account.__dict__, default=str)) if account else {},
    )
    await session.commit()
    return result
