# ADR: Redpanda decision gate

Status: DEFER (Day 11)

## Context

ECHO currently uses a bounded `asyncio.Queue` in the market pipeline and an async generator plus
deduplicating world consumer. Canonical event and bar persistence is idempotent, malformed world
events are dead-lettered into the existing database path, and live market overflow is explicit:
drop-oldest for low-value fresh-over-stale market observations, block/backpressure for replay.
Canonical events are never silently dropped.

## Evidence

- Queue capacity and dropped counts are exposed by `/api/v1/market/status` and `/metrics`.
- Market adapter and pipeline tests cover overflow, reconnect, malformed messages, and retry.
- Day 11 benchmark artifacts measure deterministic normalization, graph, forecast artifact load, and
  API paths. No cross-process consumer or persisted-offset workload has been demonstrated.

## Decision

Defer Redpanda. Do not add a broker until measurements show a need for durable replay, independent
cross-process consumers, persisted offsets, or recovery beyond the current process boundary.

## Consequences

The current queue remains bounded and easy to operate locally. A future adoption must define a
small topic taxonomy, version every message (for example `echo.canonical_event.v1`), use stable
IDs for idempotency, and include a dead-letter topic with payload hashes rather than raw secrets.
The migration trigger is evidence, not the number of services on a diagram.
