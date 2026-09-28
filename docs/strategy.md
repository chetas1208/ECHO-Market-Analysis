# ECHO Residual Propagation Strategy

`echo-rp-v1` is a deterministic registered policy. It does not call an LLM and
it does not treat ShockGraph exposure or a heuristic score as a probability.

At a frozen cutoff it computes:

```text
opportunity = |graph exposure| * event confidence * forecast confidence
```

The policy then requires directional forecast probability, a bounded quantile
interval, graph/event confidence, compatible cause direction, fresh market data,
and portfolio capacity. Direction is LONG for a positive q50 and SHORT for a
negative q50. Otherwise it returns ABSTAIN with machine-readable reason codes.

Underabsorption is explicitly defined as:

```text
absorption_ratio = abs(observed residual move) / max(abs(forecast q50), epsilon)
```

The v1 threshold is `0.75`. A residual z-score at or above `2.5` is considered
already priced unless the caller explicitly supplies an audited override. The
current fixture's residual is a cutoff feature proxy; it is not represented as
a cumulative event move without historical evidence.

Trading horizons are 1D, 2D, and 5D. 10D and 20D remain forecast outputs only.
The default risk profile is 0.75% risk per trade, 20% single-name notional, five
concurrent positions, two positions per sector, 30% sector gross, 100% total
gross, and a 5% drawdown kill switch. Costs, delays, stop, hedge, and confirmation
variants are versioned configuration, not hidden constants.
