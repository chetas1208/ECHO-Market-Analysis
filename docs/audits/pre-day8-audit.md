# Pre-Day 8 Audit

Date: 2026-09-20

## Scope

Day 8 starts from the immutable Day 7 prediction ledger and deterministic bar
simulator. This audit is a boundary check, not a performance claim.

## Verified

- `docs/audits/day1-audit.md`, `day3-audit.md`, `day4-audit.md`,
  `day6-audit.md`, and `day7-audit.md` are present and were read.
- The Day 7 audit records 1,314 backend tests passed, 90 skipped, one warning;
  frontend tests were 163 passed with typecheck, lint, and build passing.
- Forecast vintages carry cutoff, feature, graph, model, OOD, and content-hash
  metadata. Actuals append separately and do not mutate a vintage.
- The Day 7 simulator already owns bar-based next-bar execution, costs, stops,
  hedging, and LONG/SHORT/NO_TRADE outcomes; Day 8 reuses that primitive.
- No sixth primary navigation tab is required; Strategy already exists.

## Findings and limits

- No defensible multi-year, timestamped historical event archive is checked in.
- The available forecasting fixture is synthetic and is suitable only for
  deterministic contract tests and smoke replay. It cannot support a claimed
  Sharpe, return, or final holdout result.
- Market providers are configured behind the normalized market-data boundary;
  no provider was silently mixed into a Day 8 performance dataset.
- Day 2 and Day 5 audit documents are not present in the repository; that
  pre-existing documentation gap is recorded rather than inferred away.

## Day 8 decision

Implement the strategy policy, replay clock, risk-aware backtester, artifact
format, API contract, and UI surface. Promote no empirical strategy until a
timestamped event archive and compatible bars are supplied.
