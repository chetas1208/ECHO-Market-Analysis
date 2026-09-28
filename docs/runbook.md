# ECHO operations runbook

## First checks

1. Read `X-Request-ID`/`X-Trace-ID` from the failing response.
2. Check `GET /api/v1/health`, `GET /api/v1/ready`, `GET /api/v1/ops/status`, and `GET /metrics`.
3. Confirm data and execution modes; replay must never be described as live.

## Market feed stale

Inspect `last_observation_at`, provider state, queue depth/capacity, dropped count, and reconnect
attempts. Do not silently switch incompatible providers. A failover must be visible as DEGRADED.
Keep execution disabled or paused until freshness and reconciliation are verified.

## World Monitor down

Keep the API and cached canonical events available. The status drawer/ops endpoint should show the
world dependency as DEGRADED or UNAVAILABLE while market intelligence remains usable. Use replay
only for deterministic demos and label it clearly.

## Database unavailable

Liveness may remain `200`; readiness must fail and data writes must stop safely. Check PostgreSQL,
pool gauges, and migration head. Do not run `db-reset` in a shared environment. Restore from a
verified dump, migrate, then validate immutable records.

## Model unavailable

Forecast status must say `FORECAST_UNAVAILABLE` or optional-model unavailable. Keep the registered
fallback and its artifact hash explicit. Do not download weights at request time and do not promote
an unmeasured model.

## Alpaca mismatch

Run reconciliation and inspect unknown broker orders, missing local orders, fill/quantity, and
position mismatches. Mark DEGRADED and pause paper execution. Never auto-correct ambiguous state.

## Trading paused

The kill switch is restart-safe through configuration and is visible in execution status and
metrics. Preserve the pause while investigating. Resume only after provider health, market
freshness, forecast validity, risk limits, and reconciliation are all independently checked.

## Alert policy

Critical: database unavailable, paper mismatch, forecast corruption, or graph hash mismatch.
Warning: stale feed, model drift, high latency, or queue lag. Ordinary reconnects are informative,
not paging events.
