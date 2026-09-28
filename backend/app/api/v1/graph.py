"""ShockGraph endpoints: immutable snapshots, inspection, and event exposure."""

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import SessionDep
from app.core.errors import NotFoundError
from app.graph.propagation import PropagationConfig
from app.graph.service import ShockGraphService
from app.repositories.events import EventRepository
from app.schemas.graph import GraphNeighborsResponse, GraphSnapshotsResponse

router = APIRouter(tags=["graph"])


@router.get("/graph/snapshots", response_model=GraphSnapshotsResponse)
async def list_graph_snapshots(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> GraphSnapshotsResponse:
    items = await ShockGraphService(session).list_snapshots(limit)
    return GraphSnapshotsResponse(items=items, total=len(items))


@router.get("/graph/snapshots/{snapshot_id}")
async def get_graph_snapshot(snapshot_id: str, session: SessionDep):
    snapshot, _, _ = await ShockGraphService(session).load_snapshot(snapshot_id)
    return snapshot


@router.get("/graph/nodes/{node_id}")
async def get_graph_node(node_id: str, session: SessionDep, snapshot_id: str | None = None):
    return await ShockGraphService(session).node(node_id, snapshot_id)


@router.get("/graph/nodes/{node_id}/neighbors", response_model=GraphNeighborsResponse)
async def get_graph_neighbors(node_id: str, session: SessionDep, snapshot_id: str | None = None):
    snapshot, nodes, edges = await ShockGraphService(session).neighbors(node_id, snapshot_id)
    return GraphNeighborsResponse(snapshot=snapshot, nodes=nodes, edges=edges)


@router.get("/graph/edges/{edge_id}")
async def get_graph_edge(edge_id: str, session: SessionDep, snapshot_id: str | None = None):
    return await ShockGraphService(session).edge(edge_id, snapshot_id)


async def _event_projection(
    event_id: str,
    session: SessionDep,
    snapshot_id: str | None,
    max_depth: int,
    limit: int,
):
    event = await EventRepository(session).get(event_id)
    if event is None:
        raise NotFoundError(f"Event '{event_id}' not found")
    config = PropagationConfig(max_depth=max_depth, max_results=limit)
    return await ShockGraphService(session).project_event(
        event, snapshot_id=snapshot_id, config=config
    )


@router.get("/events/{event_id}/exposures")
async def get_event_exposures(
    event_id: str,
    session: SessionDep,
    snapshot_id: str | None = None,
    max_depth: Annotated[int, Query(ge=1, le=3)] = 3,
    limit: Annotated[int, Query(ge=1, le=50)] = 25,
):
    return await _event_projection(event_id, session, snapshot_id, max_depth, limit)


@router.get("/events/{event_id}/graph")
async def get_event_graph(
    event_id: str,
    session: SessionDep,
    snapshot_id: str | None = None,
    max_depth: Annotated[int, Query(ge=1, le=3)] = 3,
    limit: Annotated[int, Query(ge=1, le=50)] = 25,
):
    return await _event_projection(event_id, session, snapshot_id, max_depth, limit)
