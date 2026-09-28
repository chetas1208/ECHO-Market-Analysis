# Leakage-safe historical replay

The Day 8 engine processes cases in `(decision timestamp, event id, symbol)`
order. The event clock documents the equal-timestamp order as market observation,
event arrival, forecast, decision, execution, then position update. Strategy code
receives only the frozen event/graph/market/forecast snapshot; execution bars are
strictly after the decision timestamp and the shared Day 7 simulator supplies
next-bar fills, costs, stops, and optional hedges.

Cases are split chronologically by event group. A final holdout must remain
untouched by selection. Metrics requiring meaningful samples, including Sharpe,
Sortino, and annualized values, are returned as `null` with
`INSUFFICIENT_DATA` when the evidence is too small. Every artifact run contains
`config.json`, `metrics.json`, `trades.csv`, `equity.csv`, `drawdown.csv`,
`metadata.json`, and `report.md`; an existing run directory is never overwritten.

The API exposes only the registered `fixture_validation` dataset in this
repository. It is an integration smoke dataset and is always labeled
`HISTORICAL_REPLAY`; it is not a historical performance result. Real event
archives must declare provider, timestamp coverage, symbol exclusions, corporate
action treatment, bar granularity, dataset hash, and train/validation/test dates
before promotion.

`make backtest-final` creates an immutable run directory and refuses to overwrite
an existing run. `make backtest-verify` reruns the same deterministic fixture and
compares every JSON, CSV, metadata, and report artifact without mutating the
original directory.
