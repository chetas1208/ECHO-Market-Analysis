# Day 7 audit — Immutable Prediction Ledger + Simulator

Date: 2026-09-20  
Scope: immutable forecast vintages, append-only actuals, CAR evaluation,
deterministic paper simulation, portfolio state, API, UI, and audit export.

## 1. Pre-Day 7 audit

`docs/audits/pre-day7-audit.md` records the source-of-truth review and baseline.
The existing `forecast_runs`/`forecast_points` ledger and PostgreSQL immutability
function were preserved. Missing historical `day2-audit.md` and
`day5-audit.md` files were not fabricated. PostgreSQL-backed Alembic tests
recreated the test database from clean state; the shell image lacks the
`pg_isready` utility, so no standalone readiness claim is made.

## 2. Ledger architecture

Migration `0008_prediction_ledger_simulator` extends the existing tables with
artifact/config/engine metadata, OOD/abstention state, event and feature
snapshots, request/idempotency hashes, content hashes, expected CAR, and risk.
It adds:

- `forecast_actuals` for immutable market observations;
- `forecast_evaluations` for append-only evaluation snapshots;
- `simulated_trades` for immutable trade plans and outcomes;
- `simulated_trade_events` for state transitions;
- `paper_positions` for append-only position marks;
- `portfolio_snapshots` for historical account valuation.

`PredictionLedgerService` owns creation, idempotency, listing, actual append,
evaluation, integrity verification, and JSON export. `TradeSimulationService`
owns bar loading, plan creation, event recording, and derived portfolio state.

## 3. Immutability evidence

The database applies row UPDATE/DELETE and statement TRUNCATE triggers to every
Day 7 append-only table. Existing forecast rows retain the same protection.
The automated SQL test attempts:

```sql
UPDATE simulated_trades SET status = 'CLOSED' WHERE id = :id;
DELETE FROM simulated_trades WHERE id = :id;
```

Both are rejected with the database error form:
`table "simulated_trades" is an immutable, append-only ledger: UPDATE/DELETE is
not allowed`. Existing forecast-run and forecast-point update/delete/truncate
tests also pass.

There are no PATCH, PUT, or DELETE forecast routes. A retry with the same
idempotency key/request hash returns the original vintage; a different payload
under the same key is rejected.

## 4. Forecast identity and integrity

The ledger preserves event snapshot, graph snapshot ID, model version, model
artifact hash, feature version/hash/snapshot, config hash, engine version,
cutoff, issuance time, OOD/abstention state, and all frozen points. The content
hash is deterministic over that metadata and q10/q50/q90/probability/risk
points. The passing ledger test confirms a duplicate create returns the same ID
and `verify_integrity` returns `VALID` with matching stored/computed hashes.

## 5. Actual tracking

`POST /api/v1/forecasts/{id}/actuals` appends observations only when their
market timestamp is after the forecast cutoff. Observation hashes and the
`(forecast_run_id, horizon, market_timestamp)` unique constraint prevent
duplicate target observations. `ForecastActualCollector` resolves due NYSE
target sessions and uses the same Day 6 CAR target function and cutoff betas.
`make backfill-actuals FORECAST_ID=... AS_OF=...` is the deterministic job
entrypoint.

## 6. Evaluation

Evaluation reads frozen points and actual abnormal returns, never raw return as a
substitute. It reports `PENDING` until a target CAR exists, then computes
absolute/squared error, direction, q10–q90 interval coverage, q10/q50/q90
pinball losses, and positive-CAR Brier contribution. The passing test records a
1D abnormal return of `0.02` against a frozen `q50` of `0.01`, producing
absolute error `0.01`.

## 7. Simulator and risk controls

`echo-sim-v1` supports LONG, SHORT, and explicit NO_TRADE. Default entry rules
require in-distribution data, no abstention, minimum q50 magnitude, acceptable
interval width, and directional probability threshold. Sizing uses risk budget,
volatility-derived stop distance, maximum position percentage, and initial
equity. Commission, spread, and slippage are included. Optional hedges and
strategy/config hashes are frozen into the trade plan.

Entry is the first bar strictly after the decision timestamp; exit is the first
bar at or after the target timestamp. Stops are captured at creation and are
checked conservatively before horizon exit. No future bar can create an entry.

## 8. Portfolio accounting

The derived paper account reports initial equity, cash, gross/net exposure,
equity, realized P&L, unrealized P&L, and trade count. `portfolio_snapshots`
preserves marks rather than overwriting them. No broker order is sent.

## 9. API and UI

Implemented:

- `POST/GET /api/v1/forecasts` and `GET /api/v1/forecasts/{id}`;
- `POST/GET /api/v1/forecasts/{id}/actuals`;
- `GET /api/v1/forecasts/{id}/evaluation`;
- `GET /api/v1/forecasts/{id}/integrity`;
- `GET /api/v1/forecasts/{id}/export`;
- `POST /api/v1/forecasts/{id}/simulate`;
- `GET /api/v1/simulations/{id}`;
- `GET /api/v1/portfolio/simulated`.

The existing Forecasts primary tab now contains a vintage ledger, vintage
detail/provenance, frozen horizon points, pending/complete evaluation state,
and deterministic simulation action. It does not add a sixth primary tab or
present paper trades as live execution.

## 10. E2E and performance evidence

The transactional Day 7 test scenario creates one event-conditioned vintage,
retries it idempotently, verifies its content hash, appends a post-cutoff actual,
and evaluates it in CAR units. Pure simulator coverage includes long, short,
NO_TRADE, missing-entry, next-bar, and cost behavior.

A deterministic long smoke with prices `100 -> 102`, 10 bps commission, and
configured spread/slippage produced entry `100.0750`, gross P&L `369.4229`,
costs `40.3694`, and net P&L `329.0535`. 1,000 identical pure simulations
completed in `36.92 ms` locally (`0.03692 ms` mean); this is a unit-level
measurement, not a production latency SLO.

## 11. Verification

- Backend Ruff format/check: passed.
- Backend: **1314 passed, 90 skipped, 1 warning**.
- Frontend: **163 passed** across 20 test files.
- Frontend typecheck, ESLint, and Next production build: passed.
- Migration drift check: passed.
- Day 7 focused ledger/simulator tests: passed.

## 12. Limitations and Day 8 handoff

The current workspace still lacks a production historical event/company dataset,
local Chronos checkpoint, and broker execution integration. Actual backfill
requires market observations covering the forecast cutoff through target
sessions. Live simulation and paper positions remain internal domain state.

Day 8 consumes immutable forecast vintages, frozen model/graph/feature
references, actual observations, evaluations, simulated trades, portfolio
snapshots, and performance history. Day 8 was not started.
