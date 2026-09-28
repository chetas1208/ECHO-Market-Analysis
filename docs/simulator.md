# Paper Trade Simulator

The Day 7 simulator is a deterministic, paper-only calculation over a frozen
forecast vintage. It does not send Alpaca or other broker orders.

## Signal rules

The default `echo-sim-v1` configuration abstains when the forecast is OOD,
abstained, has insufficient q50 magnitude, has an interval wider than the
configured maximum, or fails the positive/negative probability threshold.
Otherwise q50 and probability determine `LONG` or `SHORT`. `NO_TRADE` is stored
as a real simulation result with an explicit reason.

## Execution and sizing

- Decision time is the frozen forecast issuance timestamp.
- Entry uses the first bar strictly after decision time, at its open.
- Exit uses the first bar at or after the chosen target timestamp, at its close.
- The same decision bar is never used for entry.
- Position size is volatility-aware and capped by risk budget and maximum
  position percentage; q50 cannot create unlimited exposure.
- A fixed volatility stop is captured at trade creation and is not recomputed
  from later volatility.
- Configurable commission, spread, and slippage are included in net P&L.
- Optional hedge symbol and ratio are stored in the immutable trade plan.

Trade plans are append-only. `simulated_trade_events` records planned/open/
terminal state transitions without rewriting the original plan. Portfolio
accounting exposes cash, gross exposure, net exposure, realized P&L, unrealized
P&L, and equity; `portfolio_snapshots` preserves historical marks.

## API

- `POST /api/v1/forecasts/{id}/simulate` — create a deterministic simulation.
- `GET /api/v1/simulations/{id}` — load the immutable simulated trade.
- `GET /api/v1/portfolio/simulated` — current derived paper account state.
- `make backfill-actuals FORECAST_ID=... AS_OF=...` — append due CAR actuals.

The UI separates prediction, actual evaluation, and simulation. A forecast is
not colored as profit merely because q50 is positive, and a paper simulation is
not presented as execution.
