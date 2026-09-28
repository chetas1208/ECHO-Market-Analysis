# ECHO Residual Propagation

Status: deterministic Day 8 strategy specification; no live-performance claim.

## Rules

- Universe: liquid equities from `backend/config/universe.yaml`; benchmarks are available only for hedge and comparison.
- Inputs: timestamped event, ShockGraph exposure/confidence, cause direction, market/sector residuals, volume, and a frozen forecast vintage.
- Long: positive q50, probability at least 0.60, graph exposure at least 0.20, graph/event confidence at least 0.60, interval width at most 0.25, underabsorption ratio at most 0.75, moderate market confirmation, and no OOD/stale/already-priced state.
- Short: the symmetric negative-q50 and negative-probability rule.
- Abstain: any missing input, incompatible cause direction, insufficient confidence, wide interval, absorbed/already-priced move, stale market, OOD state, unsupported horizon, or portfolio limit.
- Entry: the first bar strictly after the completed decision bar; no same-bar fill.
- Horizon: 1D, 2D, or 5D. The forecast may expose 10D/20D, but this policy does not trade them.
- Sizing: 0.75% risk per trade, 20% maximum position, five concurrent positions, two per sector, 30% sector gross, 100% total gross.
- Exit: 1.5 volatility-risk stop or selected horizon, with transaction costs and slippage applied.
- Hedge: none in the frozen v1 profile; SPY/sector hedges are separate variants.
- Kill switch: no new entries after a 5% portfolio drawdown or configured daily loss limit.

The backtester is authoritative. This file is the platform-neutral handoff to Conviction.
