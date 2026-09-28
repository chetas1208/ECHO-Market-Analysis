# Day 11 production hardening audit

Recorded: 2026-09-21  
Version: `ECHO 0.2.0-dev`  
Scope: post-hackathon operational foundation; no feature expansion

## 1. Hackathon release integrity

`make verify-release` passed with zero differences. The frozen manifest is
`artifacts/releases/hackathon-final/manifest.json` and records SHA-256 values for the Day 10
release manifest, test summary, strategy config, and forecast artifact. Historical files under
`artifacts/release/`, the strategy, ledger, graph snapshots, and backtest artifacts were not
modified by Day 11.

The release remains replay-only (`REPLAY`) and execution-disabled (`DISABLED`). Alpaca paper
verification remains `NOT_VERIFIED`.

## 2. Production changes

- Added a dependency-free Prometheus exposition at `/metrics` and `/api/v1/ops/metrics`.
- Added HTTP request/error/latency, DB session/ping/pool, queue, provider, world, execution,
  reconciliation, model-state/measurement-availability, and build-version metrics.
- Added trace ID propagation through `X-Trace-ID`; structured logs now support trace, event,
  forecast, graph, symbol, provider, operation, and duration fields without logging raw payloads.
- Added unified read-only dependency health at `/api/v1/ops/status` with explicit
  `HEALTHY`, `DEGRADED`, and `UNAVAILABLE` states. Liveness does not depend on optional feeds.
- Added a secondary frontend Operations route at `/ops`; no sixth primary navigation tab was added.
- Added release verification, deterministic benchmark tooling, model registry metadata, production
  deployment/architecture docs, data lifecycle policy, runbook, and ADRs.

Existing bounded queues, world dead-letter handling, idempotent execution, immutable records,
lazy optional model loading, and paper-only safety gates remain in place.

## 3. Actual measurements

Measurements are in `artifacts/benchmarks/day11/` and are deterministic local microbenchmarks on
a shared development machine. They are not live-provider or database capacity claims.

| Workload | Result | Scope |
| --- | --- | --- |
| World normalization | 996.79 events/s; p50 1.0085 ms; p95 1.0356 ms | 250 pure normalizations, no DB |
| Bounded market enqueue | 208,685.5 bars/s; 5,000 input; 4,936 explicit drops; depth 64/64 | drop-oldest queue seam |
| ShockGraph propagation | p50 0.0308 ms; p95 0.0403 ms; max 48.1056 ms | 105 nodes / 85 edges, pure propagation |
| Forecast | p50 0.2544 ms; p95 0.2790 ms | linear fallback inference, no Chronos |
| API | p50 0.3479 ms; p95 0.3808 ms | ASGI liveness, no DB/provider |
| Process memory | 115.44 MiB peak | benchmark process; optional models not loaded |

The graph maximum is an outlier and is retained rather than hidden. ModernFinBERT and Chronos
RSS/warm inference are `NOT_LOADED`/`UNAVAILABLE` in this run. Existing model documentation has
prior separate ModernFinBERT measurements; they are not silently mixed into this benchmark.

## 4. Redpanda decision

**DEFER.** The current bounded in-process queue demonstrates explicit backpressure/drop behavior,
and no cross-process consumers, persisted offsets, or recovery requirement has been measured. See
`docs/adr/ADR-redpanda.md`. The next adoption gate is a measured durability or process-scaling need.

## 5. Rust decision

**DEFER.** The measured pure Python graph and normalization paths are fast at the current fixture
size, and no production hotspot has been identified. See `docs/adr/ADR-rust.md`.

## 6. Reliability

- Existing provider supervisor tests cover disconnect/reconnect, stale state, malformed input,
  bounded overflow, and failover.
- Existing world pipeline tests cover malformed events and dead-letter persistence.
- Existing execution tests prove kill-switch rejection and no broker call on dry-run/rejection.
- New observability tests cover metrics rendering, trace headers, and liveness with a failed DB.
- The runtime keeps market/world provider failure from taking down liveness; unified status reports
  the degradation instead.
- A full external DB restart/Alpaca reconciliation test is not claimed in this local pass.

## 7. Database

The async engine uses `pool_size=5`, `max_overflow=5`, `pool_pre_ping=True`, and a five-second
connect timeout. Pool size, checked-out connections, overflow, session duration, and ping latency
are exposed as metrics. Streaming workers use short sessions for persistence; no long-running
transaction was introduced.

Backup/restore procedure is documented in `docs/production-deployment.md`. A restore was **not
run** in this pass because the local PostgreSQL client tools (`pg_isready`, `pg_dump`, and
`pg_restore`) were unavailable and no running compose database was exposed. The required next
evidence is a controlled `pg_dump`/`pg_restore` against an isolated database followed by
migration-head and immutable-record validation.

## 8. Models

`artifacts/models/registry.json` records the active linear fallback forecast artifact and marks
Chronos/ModernFinBERT experimental. Promotion is explicit and never automatic. No model weights
are updated during execution. The model-serving ADR defers a process split until real RSS or warm
latency exceeds the local budget.

## 9. Execution

Execution remains `DISABLED` by default and `LIVE` is rejected by settings. Existing idempotency,
append-only order/fill/reconciliation records, and mismatch-as-DEGRADED behavior remain active.
Kill-switch state is visible in execution status and metrics and is restart-safe through the
configuration boundary. Alpaca PAPER credentials were not available, so broker reconciliation is
`NOT_VERIFIED`, not PASS.

## 10. Security

No new runtime dependency or network call was added. Metrics and ops responses exclude secrets and
raw event/news payloads. Trace/request IDs are validated and bounded. The frontend receives only
the read-only operational view. Critical dependency pinning remains represented by the existing
lockfiles; no blind dependency upgrade was performed. A full external SCA/SBOM scan remains an
environment-dependent follow-up.

## 11. Tests

| Gate | Result |
| --- | --- |
| Release hash verification | PASS |
| New observability tests | 3 passed |
| Existing health/middleware regression set | 13 passed |
| Backend Ruff | PASS |
| Frontend lint/typecheck | PASS |
| Full backend suite | 1331 passed, 90 skipped, 1 warning |
| Frontend tests/build | 163 passed; lint/typecheck/build PASS |

The final handoff records the exact final gate output above.

## 12. Known risks

- Live provider capacity, World Monitor quotas, Alpaca credentials, Chronos, and ModernFinBERT
  production resource use are not verified locally.
- The benchmark suite does not represent PostgreSQL write throughput, websocket/browser load, or
  multi-process provider fan-out.
- The current kill switch is configuration-controlled rather than a separate operator control
  plane; no dynamic pause endpoint was added.
- Backup restore and external dependency security scanning remain unexecuted evidence.

## 13. Next recommended work

**Scaling.** First run an isolated PostgreSQL write/load and API concurrency profile at 50, 100, and
250 symbols, then decide whether workload separation or a durable broker is justified. Do not start
that track as part of Day 11.
