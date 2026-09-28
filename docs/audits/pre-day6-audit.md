# Pre-Day 6 audit — Forecasting Engine

Date: 2026-09-20.

## Scope inspected

- Read `Plan.md`, `Milestones.md`, `decisions.md`, `seed.md`, `UI.md`, the Day 1–5
  contracts/audits, `docs/market-data.md`, `docs/models.md`, `docs/shockgraph.md`,
  and `docs/cause-engine.md`.
- Inspected the repository, current API/router, immutable forecast-ledger models,
  market observations, causal graph snapshots, and Forecasts tab placeholder.
- Git history/remote are unavailable in this workspace; status is tracked from the
  current working tree.

## Existing contracts verified

- Forecast ledger tables already target cumulative abnormal returns and are protected
  by append-only database triggers. Day 6 does not change that migration.
- Market features are causal and use shifted rolling baselines; bars are normalized
  UTC observations with provider provenance.
- ShockGraph snapshots are content-addressed and integrity-checked before projection.
- Cause Engine realtime paths enforce event-ingestion and graph-snapshot cutoffs.
- Forecasts remains an existing primary tab; no new navigation tab is introduced.

## Baseline evidence

- Backend before Day 6: **1,301 passed, 90 skipped, 1 warning** after Day 5.
- Frontend before Day 6: **163 passed** with typecheck, lint, and build passing.
- Chronos-2, LightGBM, and `arch` are not installed in the default backend runtime;
  no local Chronos checkpoint is cached. The implementation therefore exposes these
  as explicit optional statuses and uses only an identified linear/HAR fallback.
- Forecast ledger rows were not modified. Day 7 owns permanent forecast creation.

## Day 6 boundary

The additive scope is CAR target construction, cutoff-bound features, chronological
event-group splitting, quantile inference, HAR volatility context, calibration/OOD/
abstention, preview/status APIs, Forecasts UI, reproducible commands, and audit
evidence. No Day 7 ledger-vintage or simulator code is included.
