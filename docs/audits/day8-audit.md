# Day 8 Audit

Date: 2026-09-20

## Implementation evidence

- Versioned `echo-rp-v1` LONG / SHORT / ABSTAIN policy with underabsorption,
  already-priced, confirmation, OOD, confidence, and portfolio gates.
- Explicit replay clock and strict cutoff validation; execution uses the Day 7
  next-bar simulator rather than duplicate trade logic.
- Chronological case ordering, per-event case hashes, deterministic run IDs,
  transaction costs, stops, portfolio limits, daily loss guard, and drawdown kill.
- Independent artifacts: config, metrics, trades, equity, drawdown, metadata,
  and report. Existing run directories are never overwritten.
- Registered API routes: `POST /api/v1/backtests`, `GET /api/v1/backtests`,
  `GET /api/v1/backtests/{id}`, and `GET /api/v1/backtests/{id}/trades`.

## Dataset and performance boundary

The checked-in dataset is `fixture_validation`, a deterministic synthetic smoke
fixture from `app.backtesting.datasets.fixture_cases`. It contains 18 cases,
two symbols, one event class, and replay bars generated for contract validation.
It is not a real historical event archive. Therefore no Sharpe, final-holdout,
baseline, ablation, or conviction performance claim is promoted here. The replay
reports `INSUFFICIENT_DATA` when the trade sample is below 20.

The reproducible smoke run is `0e4a33a922f147aefc17` under
`artifacts/backtests/`: 18 trades, 1.2903% total return, 0.2182% maximum
drawdown, 83.33% hit rate, 3.0542 profit factor, 7.4118 trades/week, and
0.9993 average holding days. Sharpe, Sortino, annualized return, and Calmar are
`null` because this is below the minimum sample and is synthetic. These numbers
are contract evidence only, not a market result.

The bounded research command evaluates S0–S6, four ablations, and 1x/2x/3x
cost variants (14 trials). The smoke fixture is intentionally not used to select
a promoted strategy; no real validation or final holdout was opened.

## Required follow-up before empirical promotion

Supply a timestamped event archive and compatible market bars, freeze a strategy
after validation, run the untouched final holdout once, and attach baseline,
ablation, cost/delay robustness, threshold sensitivity, bootstrap uncertainty,
10-trading-day window, event-class, horizon, regime, and concentration reports.

Day 9 is intentionally not implemented.
