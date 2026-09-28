# ECHO — technical judge brief

## Problem and thesis

Markets absorb headlines quickly, but the economic consequences of an event
propagate through channels at different speeds. ECHO estimates that propagation
gap rather than treating sentiment as a trade.

## Architecture

World Monitor and market feeds produce canonical events and observations.
ShockGraph maps events through economic channels and company exposure. Cause
Engine investigates market shocks. Forecasts produce calibrated abnormal-return
distributions with immutable provenance. A deterministic strategy/risk gate
chooses `LONG`, `SHORT`, or `ABSTAIN`, and only `PAPER_TRADE` can reach the
paper-execution adapter.

## Evidence

- Strategy: frozen `echo-rp-v1`; config hash is recorded in the release manifest.
- Graph: checked-in `echo-graph-v1` seed with 105 nodes and 85 edges.
- Replay: run `0e4a33a922f147aefc17`, 18 synthetic cases, strict future-access
  policy, and append-only artifacts.
- Integrity: forecast vintages and graph snapshots are protected by database
  constraints/triggers; a new observation creates evaluation evidence rather
  than rewriting the vintage.

## Results and limitations

The checked-in replay is contract evidence, not a market-performance claim. It
reports 1.2903% total return, 0.2182% max drawdown, 83.33% hit rate, and 18
trades, with `INSUFFICIENT_DATA`; Sharpe, Sortino, annualized return, and Calmar
are intentionally null. A timestamped historical event archive is required
before empirical strategy promotion or a credible rolling two-week result.

Alpaca is paper-only and was not credential-verified in this environment. Paper
execution does not model all live-market effects such as impact, queue position,
latency, or slippage.
