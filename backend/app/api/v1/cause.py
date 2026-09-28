"""Cause Engine, bidirectional impact, and structured cluster APIs."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import AfterValidator

from app.api.deps import SessionDep
from app.cause.engine import CauseEngine
from app.cause.types import CauseMode
from app.repositories.market_events import MarketEventRepository
from app.schemas.cause import (
    CauseInvestigationOut,
    ClusterShockListOut,
    ClusterShockOut,
    MarketImpactOut,
)


def _require_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("must be timezone-aware: include a UTC offset or 'Z'")
    return value.astimezone(UTC)


AwareDatetime = Annotated[datetime, AfterValidator(_require_aware)]

router = APIRouter(tags=["cause"])


@router.post("/investigations/market-shock/{event_id}", response_model=CauseInvestigationOut)
async def investigate_market_shock(
    event_id: str,
    session: SessionDep,
    mode: CauseMode = CauseMode.REALTIME,
    data_cutoff_at: Annotated[AwareDatetime | None, Query()] = None,
    snapshot_id: str | None = None,
) -> CauseInvestigationOut:
    if data_cutoff_at is not None:
        if data_cutoff_at.tzinfo is None or data_cutoff_at.utcoffset() is None:
            data_cutoff_at = data_cutoff_at.replace(tzinfo=UTC)
        else:
            data_cutoff_at = data_cutoff_at.astimezone(UTC)
    result = await CauseEngine(session).investigate_market_shock(
        event_id,
        mode=mode,
        data_cutoff_at=data_cutoff_at,
        snapshot_id=snapshot_id,
    )
    return CauseInvestigationOut.model_validate(result.model_dump(mode="json"))


@router.get("/investigations/{investigation_id}", response_model=CauseInvestigationOut)
async def get_investigation(investigation_id: str, session: SessionDep) -> CauseInvestigationOut:
    result = await CauseEngine(session).get_investigation(investigation_id)
    return CauseInvestigationOut.model_validate(result.model_dump(mode="json"))


@router.get("/events/{event_id}/market-impact", response_model=MarketImpactOut)
async def get_event_market_impact(
    event_id: str,
    session: SessionDep,
    data_cutoff_at: Annotated[AwareDatetime | None, Query()] = None,
    snapshot_id: str | None = None,
) -> MarketImpactOut:
    result = await CauseEngine(session).analyze_world_event(
        event_id, data_cutoff_at=data_cutoff_at, snapshot_id=snapshot_id
    )
    return MarketImpactOut.model_validate(result)


@router.get("/market/clusters", response_model=ClusterShockListOut)
async def list_market_clusters(
    session: SessionDep,
    as_of: Annotated[AwareDatetime | None, Query()] = None,
    data_cutoff_at: Annotated[AwareDatetime | None, Query()] = None,
    snapshot_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> ClusterShockListOut:
    repository = MarketEventRepository(session)
    latest = await repository.list_market_shocks(1)
    if as_of is None:
        if not latest:
            return ClusterShockListOut(items=[], total=0)
        as_of = latest[0].timestamp
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        as_of = as_of.replace(tzinfo=UTC)
    else:
        as_of = as_of.astimezone(UTC)
    cutoff = data_cutoff_at or datetime.now(UTC)
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        cutoff = cutoff.replace(tzinfo=UTC)
    else:
        cutoff = cutoff.astimezone(UTC)
    engine = CauseEngine(session)
    resolved_snapshot = await engine._snapshot_id(
        cutoff=cutoff, mode=CauseMode.REALTIME, requested=snapshot_id
    )
    clusters = await engine.detect_market_clusters(
        as_of=as_of, data_cutoff_at=cutoff, snapshot_id=resolved_snapshot
    )
    items = [ClusterShockOut.model_validate(item.model_dump(mode="json")) for item in clusters]
    return ClusterShockListOut(items=items[:limit], total=min(len(items), limit))
