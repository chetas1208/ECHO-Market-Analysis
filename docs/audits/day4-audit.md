# Day 4 audit — ShockGraph

Date: 2026-09-20. This audit records the implemented ShockGraph state and the
validation evidence for the Day 4 boundary. Day 5 was not started.

## Pre-Day-4 regression

- PostgreSQL was verified healthy through the documented private rootless Docker
  daemon. A dedicated `echo_day4_test` database was used for snapshot and API
  evidence; the shared development database was not modified.
- The pre-implementation baseline was 1,283 backend tests passed and 90 skipped,
  with 163 frontend tests passed plus typecheck, lint, and production build.
- `docs/audits/day2-audit.md` remains absent; this was already recorded as a
  historical audit gap in the Day 3 audit. The existing Day 1–3 regression suite
  remained green after the additive Day 4 work.
- No Git history or remote was available in the workspace, so history comparison
  is not an available audit source.

## Graph size and taxonomy

`python scripts/validate_graph.py` passed with:

```text
valid graph_version=echo-graph-v1 nodes=105 companies=52 edges=85
```

Node counts:

| Type | Count |
| --- | ---: |
| company | 52 |
| channel | 19 |
| commodity | 8 |
| geography | 8 |
| sector | 7 |
| technology | 7 |
| infrastructure | 4 |
| Total | 105 |

Edge counts from the validated seed:

| Relationship | Count |
| --- | ---: |
| CHANNEL_EXPOSURE | 32 |
| TECHNOLOGY_DEPENDENCY | 18 |
| MEMBER_OF_SECTOR | 8 |
| PRODUCES_COMMODITY | 8 |
| CONSUMES_COMMODITY | 4 |
| GEOGRAPHIC_EXPOSURE | 4 |
| COMPETITOR_OF | 3 |
| DEPENDS_ON_ROUTE | 2 |
| SUPPLIER_OF | 2 |
| COMPLEMENT_TO | 1 |
| CUSTOMER_OF | 1 |
| RISK_SIMILARITY | 1 |
| SUBSTITUTE_FOR | 1 |
| Total | 85 |

The fixture includes the required liquid, shock-sensitive universe across
semiconductors, technology, energy, airlines, defense, cybersecurity, finance,
and industrial/logistics names. Every validated edge has a non-empty structured
provenance object inherited from the explicitly marked `MANUAL_CURATED` seed
source; no edge is derived from price correlation.

## Storage and snapshot evidence

Graph truth is relational PostgreSQL state in `graph_nodes` and `graph_edges`.
Immutable historical copies are stored in `graph_snapshots`,
`graph_snapshot_nodes`, and `graph_snapshot_edges`. The latest dedicated test
snapshot was created by the explicit graph snapshot command:

```text
snapshot_id=gs_940908830291ae1f51d2
graph_version=echo-graph-v1
nodes=105
edges=85
content_hash=940908830291ae1f51d23907b86f58f604c4b6aba98dd1feb33a7dec7576bb56
```

The earlier 79-edge snapshot remains addressable as
`gs_17ddde5fb769ea01cd68`, demonstrating that a new seed state creates a new
content-addressed snapshot rather than silently rewriting history. Snapshot
tables use always-enabled PostgreSQL mutation triggers. Direct update and
delete attempts against the latest snapshot were both blocked with SQLSTATE
`23001`.

## Propagation and deterministic E2E

The implementation maps canonical event economic channels to channel nodes,
enumerates directed simple paths to depth 3 by default, applies signed weight,
confidence, and exponential depth decay, then bounds aggregate exposure with
`tanh`. Exposure confidence is returned separately. Unknown channels are
reported in `unmapped_channels`; they do not fail the request.

For the persisted `evt_day4_api` Hormuz fixture, two identical API requests
returned the same response byte-for-byte. Both response bodies had SHA-256:

```text
b6958e269f4881ad427f16a92a68bcdde2121b9796ebb531d0898f9fbf1a8946
```

The response referenced `gs_940908830291ae1f51d2` and returned this selected
exposure evidence:

| Symbol | Exposure | Confidence | Direction |
| --- | ---: | ---: | --- |
| DAL | -0.845381 | 0.985273 | negative |
| UAL | -0.833141 | 0.985273 | negative |
| XOM | +0.799661 | 0.956726 | positive |
| CVX | +0.785144 | 0.956726 | positive |
| LNG | +0.302862 | 0.734400 | positive |

The selected paths include channel-to-company direct paths and channel → Brent
crude → company explanation paths, with edge IDs and relationship types.

## API and UI evidence

Implemented endpoints:

- `GET /api/v1/graph/snapshots`
- `GET /api/v1/graph/snapshots/{snapshot_id}`
- `GET /api/v1/graph/nodes/{node_id}`
- `GET /api/v1/graph/nodes/{node_id}/neighbors`
- `GET /api/v1/graph/edges/{edge_id}`
- `GET /api/v1/events/{event_id}/exposures`
- `GET /api/v1/events/{event_id}/graph`

The existing Graph primary tab is now the ShockGraph workspace. It loads a
selected canonical event, renders the reachable event → channel → economic node
→ company subset as an accessible SVG graph, supports depth and positive/
negative filters, exposes node/edge inspection and provenance, and ranks
companies with direction, exposure, confidence, and top reason. It uses a
page-specific CSS module and keeps the existing navigation and design tokens.
The UI has no BUY/SELL output.

## Tests and performance

- Backend full regression: **1,291 passed, 90 skipped, 1 existing warning** in
  67.04 seconds.
- Backend graph plus Alembic checks: **9 passed**.
- Backend Ruff check and format check: **passed**.
- Frontend: **163 passed** across 20 test files.
- Frontend typecheck, ESLint, and production build: **passed**.
- Live API health: `GET /api/v1/health` returned `{"status":"ok"}`.
- Live event graph HTTP timings on the 105-node/85-edge snapshot were 128.239 ms
  cold, then 30.547 ms and 26.869 ms on warm cached requests.

## Known limitations

- The initial graph is a deliberately curated seed, not complete global supply
  chain coverage. Provenance is explicit manual-curation metadata and should be
  replaced or expanded through reviewed source artifacts.
- Propagation is an explainable bounded heuristic, not a calibrated return
  forecast. Relationship signs encode directional path semantics and do not
  claim expected percentage returns.
- The current active/latest selection is database-order based when a caller
  omits `snapshot_id`; forecast creation has not yet attached a snapshot ID.
- World Monitor live credentials and external provider availability remain
  outside this deterministic replay/audit environment.

## Day 5 handoff

Day 5 Cause Engine should consume, without changing the graph contract:

```text
MarketShock
  + Canonical World Event
  + economic channels
  + graph_snapshot_id
  + ranked ShockGraph exposures and explanation paths
  + event timestamps
      -> Cause Engine
```

The graph snapshot ID, signed exposure, separate confidence, and explanation
paths are the reproducible inputs. No Cause Engine implementation was started.
