"""Public ShockGraph API response schemas."""

from pydantic import BaseModel

from app.graph.types import GraphEdgeValue, GraphNodeValue, GraphSnapshotValue


class GraphSnapshotsResponse(BaseModel):
    items: list[GraphSnapshotValue]
    total: int


class GraphNeighborsResponse(BaseModel):
    snapshot: GraphSnapshotValue
    nodes: list[GraphNodeValue]
    edges: list[GraphEdgeValue]
