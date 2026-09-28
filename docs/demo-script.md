# ECHO demo script

Target length: 3–5 minutes. Run the deterministic replay first; live feeds are
optional context and never a presentation dependency.

## Reset and launch

```bash
make demo-reset
make demo
```

The command starts with `ECHO_MARKET_PROVIDER=replay` and
`ECHO_EXECUTION_MODE=DISABLED`. The header must read `REPLAY`/`SIMULATION`,
never LIVE or real-money trading.

## One story

1. **Problem — 20 seconds.** Markets price headlines quickly, but economic
   consequences propagate unevenly through suppliers, customers, commodities,
   geography, and competitors. ECHO looks for the propagation the market has
   not absorbed yet.
2. **Event — 30 seconds.** Open Events and select the Hormuz fixture. Show its
   source evidence, severity score, economic channels, and affected companies.
3. **Graph — 40 seconds.** Open Graph. Explain the explicit event → oil/shipping
   → company relationships and provenance; these are not a random stock
   constellation.
4. **Forecast — 40 seconds.** Open Forecasts, show abnormal-return q10/q50/q90,
   horizon, and the data cutoff. Emphasize that ECHO forecasts abnormal return,
   not a magical future price.
5. **Integrity — 30 seconds.** Select a frozen vintage, advance replay, and show
   that the forecast remains unchanged while actual observations append.
6. **Decision — 30 seconds.** Open Strategy. Show the risk gate and the
   `PAPER_TRADE`/`NO_TRADE` boundary. Paper execution is simulated broker
   execution, not evidence of live profitability.
7. **Results — 30 seconds.** Show the actual replay metrics, sample status,
   baselines/ablations where available, and the explicit insufficient-data
   qualifier.
8. **Close — 15 seconds.** “ECHO does not predict whether news is bullish or
   bearish. It estimates how economically meaningful information should
   propagate through connected companies, measures how much of that impact the
   market has already absorbed, and acts only on the remaining propagation gap.”

## Recovery

- API unavailable: keep the UI in `OFFLINE` and use the replay artifacts; do not
  describe the data as live.
- World provider unavailable: market/replay panels remain valid.
- Alpaca unavailable: simulation remains available; do not enable paper mode.
- To return to a known state, stop the processes and rerun `make demo-reset`.
