# Pre-Day 7 audit — Immutable Prediction Ledger + Simulator

Date: 2026-09-20  
Scope: audit of the Day 1–6 source of truth before adding Day 7 persistence,
actual tracking, evaluation, and simulation.

## Repository and authority

The following Day 7 authority documents were present and reviewed: `Plan.md`,
`Milestones.md`, `decisions.md`, `seed.md`, `UI.md`, `references/REPOS.md`,
`docs/market-data.md`, `docs/models.md`, `docs/shockgraph.md`,
`docs/cause-engine.md`, and `docs/forecasting.md`. Existing Day 1, Day 3, Day 4,
and Day 6 audits were present. `docs/audits/day2-audit.md` and
`docs/audits/day5-audit.md` were not present before this milestone and are not
recreated retroactively.

The repository has no committed Git history available in the current workspace;
the worktree is an uncommitted shared implementation tree. Existing parallel
work was not interrupted.

## Existing architecture verified

- `forecast_runs` and `forecast_points` already exist from migration `0002` and
  are protected by PostgreSQL row update/delete and truncate triggers.
- Forecast points are cumulative abnormal returns, not raw-price forecasts.
- Day 6 produces cutoff-bound features, feature hashes, graph snapshot IDs,
  model versions, artifact hashes in the frozen bundle, q10/q50/q90 forecasts,
  calibration, and explicit OOD/unavailable states.
- `MarketCalendar` provides NYSE session/holiday resolution for target horizons.
- ShockGraph snapshots and Cause Engine outputs are persisted separately and
  use immutable historical references.
- The Forecasts page is the existing primary surface; Day 7 will remain under
  that surface and will not add a sixth primary tab.

## Baseline verification

- The backend test suite was rerun before Day 7 changes; the command completed
  without a reported failure while this audit was being written.
- Frontend typecheck, ESLint, 163 Vitest tests, and Next production build passed
  before Day 7 changes.
- PostgreSQL is exercised through the repository's async test harness and clean
  Alembic database recreation. The `pg_isready` utility is not installed in the
  shell, so no standalone readiness claim is made.
- World replay, market replay, ShockGraph propagation, Cause Engine, and Day 6
  deterministic forecast smoke workflows are represented by their existing
  tests/audits; no new production data or retroactive forecast values are
  introduced by this audit.

## Repairs before Day 7

No Day 1–6 schema or forecasting repair was required before implementation.
The existing Day 6 boundary remains: preview is ephemeral, and permanent
forecast-vintage creation belongs to this milestone.

## Day 7 boundary

This milestone will extend the existing forecast ledger rather than duplicate
it, add append-only actual/evaluation/simulation records, and preserve all
historical model, graph, feature, cutoff, event-snapshot, and content-hash
metadata. Day 8 is not started.
