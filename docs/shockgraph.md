# ShockGraph

ShockGraph maps canonical ECHO events to companies through explicit economic relationships. It is
not a stock-correlation graph, a return model, a recommendation engine, or a graph neural network.

## Taxonomy

Nodes are stable IDs in the form `type:canonical_key`: `company`, `commodity`, `geography`,
`technology`, `sector`, `infrastructure`, and `channel`. The checked-in seed contains 105 nodes,
including 52 liquid, shock-sensitive companies.

Edges are directed and use the following relationship types:

`SUPPLIER_OF`, `CUSTOMER_OF`, `COMPETITOR_OF`, `SUBSTITUTE_FOR`, `COMPLEMENT_TO`,
`EXPOSED_TO_COMMODITY`, `OPERATES_IN_GEOGRAPHY`, `GEOGRAPHIC_EXPOSURE`, `REGULATORY_EXPOSURE`,
`TECHNOLOGY_DEPENDENCY`, `RISK_SIMILARITY`, `MEMBER_OF_SECTOR`, `DEPENDS_ON_INFRASTRUCTURE`,
`DEPENDS_ON_ROUTE`, `PRODUCES_COMMODITY`, `CONSUMES_COMMODITY`, and `CHANNEL_EXPOSURE`.

Every edge has:

- `sign`: exactly `+1` or `-1`, the directional economic meaning of the hop;
- `weight`: relationship strength in `[0,1]`;
- `confidence`: belief that the relationship is valid in `[0,1]`;
- `provenance`: structured source/reference/note metadata;
- validity timestamps.

Weight and confidence are intentionally separate. No edge is created from price correlation.

## Propagation

Event `economic_channels` map to `channel:<name>` entry nodes. Unknown channels are returned in
`unmapped_channels` and do not fail the request. Direct company mentions are optional additional
entry points; normal propagation remains channel-first.

For a path `p` and channel strength `s`:

```text
direction(p) = product(edge.sign)
weight(p) = product(edge.weight)
confidence(p) = event.confidence * product(edge.confidence)
decay(p) = exp(-path_decay_lambda * (path_length - 1))
contribution(p) = s * direction(p) * weight(p) * decay(p)
```

The default maximum path depth is 3. Cycles are blocked by visited-node tracking. A company's
bounded exposure is `tanh(sum(contribution(p)))`, so exposure always remains `[-1,+1]`. Separate
exposure confidence is `1 - product(1 - path_confidence)` over retained paths. Exposure is a
structured directional score, never an expected stock return or probability.

Results sort deterministically by absolute exposure descending, confidence descending, then symbol.
Paths are retained with node IDs, edge IDs, relationship types, contribution, confidence, and depth.

## Storage and snapshots

PostgreSQL is the source of truth. `graph_nodes` and `graph_edges` hold the current validated graph.
`graph_snapshots`, `graph_snapshot_nodes`, and `graph_snapshot_edges` store immutable copies used by
requests. Snapshot IDs are content-addressed (`gs_<sha256-prefix>`); the hash canonicalizes sorted
node and edge values, including relationship, sign, weight, confidence, provenance, and validity.
The database uses always-enabled mutation triggers for historical snapshot tables.

The checked-in source artifact is `backend/data/graph/seed.json`. The reproducible change process is:

```text
edit seed.json -> make graph-validate -> run graph tests -> make graph-snapshot
```

Snapshot creation is explicit; API requests never silently create or switch snapshots. The latest
snapshot is used only when a request omits `snapshot_id`; historical IDs remain addressable.

## API and UI

- `GET /api/v1/graph/snapshots`
- `GET /api/v1/graph/snapshots/{snapshot_id}`
- `GET /api/v1/graph/nodes/{node_id}`
- `GET /api/v1/graph/nodes/{node_id}/neighbors`
- `GET /api/v1/graph/edges/{edge_id}`
- `GET /api/v1/events/{event_id}/exposures`
- `GET /api/v1/events/{event_id}/graph`

Responses are bounded by `limit` and `max_depth`. The Graph tab remains the existing third primary
tab and renders only the selected event's reachable subset. It distinguishes positive/negative
exposure, shows ranked companies, and exposes edge provenance in an inspector. It never emits BUY,
SELL, or return language.

## Limitations

The initial graph is deliberately curated and narrow. It does not claim complete global supply-chain
coverage, dynamic ownership, temporal relationship learning, or calibrated market-return impact.
Future additions must arrive through a new validated seed artifact and snapshot; Day 5 Cause Engine
may consume the snapshot ID and exposure paths but is not implemented here.
