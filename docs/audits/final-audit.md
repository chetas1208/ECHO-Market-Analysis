# ECHO final audit

Date: 2026-09-21

This is the final technical truth document for Day 10. `PASS` means locally
verified; `DEGRADED` means the boundary is safe but external verification or
production evidence is unavailable. No synthetic metric is promoted as live
performance.

## Foundation

**PASS.** FastAPI, Next.js, typed API client, PostgreSQL migrations, and local
commands are present. A clean local database migrated through `0009` and passed
`alembic check`. `make demo-reset` and `make demo` define a recoverable offline
demo path.

## Market and world

**PASS / DEGRADED by mode.** Replay and offline status are explicit and cannot
masquerade as LIVE. Clean replay startup connected the market provider and
persisted six world replay events with zero malformed events. Live
Massive/World Monitor connectivity was not verified because credentials were
unavailable.

## Graph and cause

**PASS.** `echo-graph-v1` seed validates with 105 nodes and 85 edges. Immutable
snapshot and cause/cluster/UNKNOWN paths are covered by tests.

## Forecast and ledger

**PASS / DEGRADED.** Forecast cutoffs, feature hashes, graph snapshot identity,
content hashes, and append-only ledger enforcement are implemented and tested.
The replay API resolves the checked-in synthetic linear-pinball bundle through
the explicit demo fallback path; Chronos remains optional and unavailable.
Historical vintages are never updated in place.

## Models

**DEGRADED locally.** The checked-in demo bundle is
`echo-forecast-v1-1ffa09297270` using `linear_pinball_fallback`. The
`amazon/chronos-2` baseline is unavailable because its optional package/checkpoint
is not installed. Forecast contracts, no-lookahead behavior, and unavailable
handling remain tested.

## Strategy and backtest

**PASS / DEGRADED for empirical claims.** `echo-rp-v1` is frozen and replayable.
The checked-in run has 18 synthetic trades and status `INSUFFICIENT_DATA`; no
Sharpe, holdout, or rolling two-week claim is made.

## Paper execution

**DEGRADED — NOT VERIFIED.** Execution defaults to `DISABLED`; `LIVE` is
rejected; replay dry-run proves no broker call. Alpaca credentials were absent,
so no paper order or external reconciliation was submitted.

## UI and reliability

**PASS locally.** Five primary tabs remain. Navigation is an overlay drawer with
backdrop blur, Escape/focus handling, global data/execution mode badges, loading,
empty, error, and a root page boundary. The frontend production build succeeds.

## Demo

**PASS for deterministic replay API path.** `artifacts/demo/scenarios.json`
records Hormuz, Taiwan narrative, cause, UNKNOWN, and abstention stories. The
replay API started from the migrated database, persisted six fixtures, and
returned healthy status endpoints. The full browser E2E sequence was not run in
this headless environment; the live path is optional and visibly degraded when
unavailable.

## Two-week analysis and performance

**UNAVAILABLE.** The synthetic 18-case fixture is below the evidence threshold,
so rolling 10-trading-day statistics and performance budgets are not claimed.

## Known limitations

- No external Alpaca paper verification in this environment.
- No real historical event archive; current backtest is synthetic contract
  evidence only.
- Browser-level manual/performance measurements require a running database/API
  and are not substituted with invented timings.

## Final verification counts

- Backend: **1328 passed, 90 skipped, 0 failed**, one dependency deprecation
  warning.
- Frontend: **163 passed, 0 failed**; lint, typecheck, and production build
  passed.
- Replay reproducibility: `make backtest-verify` returned `verified: true` for
  run `0e4a33a922f147aefc17`.
- Paper dry-run: `broker_called: false`.
