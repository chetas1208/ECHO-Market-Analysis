# ECHO Residual Propagation — Conviction Strategy

Strategy version: `echo-rp-v1`  
Config hash: `128191d8304211045b29cb8b7dde187286242428f0e68b5e1e99efe9b06b5602`  
Execution profile: PAPER only; the backend default is DISABLED.

## Universe

Use liquid equity symbols in `backend/config/universe.yaml`. Benchmark ETFs are not primary trade candidates. A symbol must be allowed by the execution profile, tradable, and shortable for SHORT decisions.

## Inputs and decision

Use only the frozen event, ShockGraph, cause, market, and forecast snapshot at the decision cutoff. The policy uses event confidence, signed graph exposure and confidence, cause direction, residual/volume confirmation, q10/q50/q90, probability-positive, freshness, and OOD state.

LONG requires positive q50 with abs(q50) >= 0.005, probability-positive >= 0.60, graph exposure >= 0.20, graph and event confidence >= 0.60, interval width <= 0.25, absorption ratio <= 0.75, moderate confirmation, a fresh market, and no OOD/already-priced/portfolio block.

SHORT is symmetric: negative q50 and probability-positive <= 0.40, with the same confidence, interval, absorption, confirmation, freshness, and risk requirements.

Otherwise the decision is ABSTAIN. Missing inputs, stale data, unsupported horizons, OOD, incompatible cause direction, already-priced residual z >= 2.5, wide intervals, and risk limits are explicit rejection reasons.

## Execution, sizing, and exit

Trade only 1D/2D/5D horizons. Enter on the first bar strictly after the completed decision bar. Risk 0.75% of current equity per trade; maximum single-name notional 20%; five concurrent positions; two per sector; 30% sector gross; 100% total gross.

Use a 1.5-risk-unit stop or horizon exit, with transaction costs and slippage. The frozen hedge mode is NONE. A 5% drawdown or configured daily-loss kill switch blocks new entries.

Only a `PAPER_TRADE` decision satisfying forecast validity, fresh data, risk, portfolio, account, and kill-switch checks may create an `OrderIntent`. The execution adapter is the only code allowed to call Alpaca, and `ALPACA_PAPER=true` is mandatory. Simulation fills and broker fills are stored separately.
