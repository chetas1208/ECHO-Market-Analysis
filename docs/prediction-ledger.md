# Prediction Ledger

Day 7 turns a Day 6 preview into a historical forecast vintage. The existing
`forecast_runs` and `forecast_points` tables remain the source of truth and are
extended in migration `0008`; no replacement ledger is introduced.

## Vintage identity

Each vintage preserves the event snapshot, graph snapshot ID, model version,
model artifact hash, feature version/hash/snapshot, config hash, engine version,
data cutoff, issuance time, OOD/abstention state, and a deterministic
`content_hash`. The hash covers the immutable metadata and every frozen point.
`GET /api/v1/forecasts/{id}/integrity` recomputes it and reports `VALID` or
`CORRUPT`; corruption is never repaired silently.

Retries use `idempotency_key` and a deterministic request hash. A matching retry
returns the original row. A key used with different request content is rejected.
There is no update, patch, or delete forecast endpoint.

## Actuals and evaluation

`forecast_actuals` is append-only. Observations must be after the forecast data
cutoff and carry a target horizon, market timestamp, source, and observation
hash. The actual collector uses the Day 6 CAR definition and NYSE session
calendar. It never writes forecast rows.

Evaluation returns `PENDING` until the target CAR exists and then computes MAE,
absolute/squared error, direction, q10–q90 interval coverage, three pinball
losses, and the Brier contribution for positive-CAR probability. Evaluation
records are append-only when persisted; the API also calculates them
reproducibly from frozen points and actuals.

## API

- `POST /api/v1/forecasts` — create an immutable vintage from a READY preview.
- `GET /api/v1/forecasts` and `GET /api/v1/forecasts/{id}` — list/detail.
- `POST/GET /api/v1/forecasts/{id}/actuals` — append/list observations.
- `GET /api/v1/forecasts/{id}/evaluation` — forecast-vs-reality metrics.
- `GET /api/v1/forecasts/{id}/integrity` — content-hash verification.
- `GET /api/v1/forecasts/{id}/export` — audit JSON export.

The Forecasts page contains the ledger table and vintage detail under the
existing primary tab. Forecast values are loaded from the ledger after creation;
only actual/evaluation state grows later.

## Day 7 boundary

Permanent forecast vintages are created here. Model promotion, live broker
execution, and any Day 8 workflow are outside this milestone.
