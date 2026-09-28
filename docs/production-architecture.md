# ECHO production architecture

The resource and dependency boundary is locked in [`docs/resource-plan.md`](resource-plan.md).
That document distinguishes active runtime components from optional or deferred capacity so this
architecture does not silently grow new infrastructure.

## CURRENT

```text
provider adapters -> bounded market queue -> market pipeline -> PostgreSQL
World Monitor/replay -> normalized event pipeline -> PostgreSQL
PostgreSQL graph snapshot -> cause/propagation -> forecast artifact -> strategy gates
API -> frontend / operator probes
execution service -> replay or Alpaca PAPER only -> append-only execution records
```

The API remains live when an optional provider is unavailable. `/metrics` and `/api/v1/ops/status`
make that degradation visible. Request and trace IDs are propagated through the HTTP boundary and
available to structured logs; domain services carry stable event, forecast, graph, and order IDs.

## FUTURE (not deployed)

- A durable broker only after the Redpanda decision gate is met.
- Separate ingestion/feature/event/graph/forecast/execution workers only after profiling proves a
  blocking or recovery boundary.
- A model-serving process only after actual RSS and warm inference measurements exceed the local
  budget.
- Larger universes, options, international markets, and GNNs only after the current benchmark and
  data-quality gates are strong.

The distinction is intentional: architecture diagrams do not count as deployed capabilities.
