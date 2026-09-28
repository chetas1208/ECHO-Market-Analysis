# ECHO judge Q&A

## Why is this not sentiment trading?

Sentiment is not the decision variable. ECHO uses canonical events, explicit
economic channels, graph exposure, market absorption, uncertainty, and a strict
risk gate.

## How are graph relationships known?

They are versioned seed relationships with sign, weight, confidence, and
provenance. The graph snapshot hash is carried into forecasts.

## How do you avoid lookahead?

The replay clock enforces a declared data cutoff. Features, graph snapshots, and
execution bars must be at or before the decision boundary; tests reject future
access.

## What if the event is already priced?

The absorption and confirmation gates return `ABSTAIN`/`NO_TRADE`.

## What happens when the model is wrong?

The ledger preserves the wrong prediction, the risk gate caps exposure, and
actual observations are recorded for evaluation. There is no history rewrite.

## Why Chronos, LightGBM, and not an LLM?

Chronos is a baseline for time-series behavior; LightGBM consumes structured
event/graph/market features. An LLM is not required for the deterministic
forecasting or audit boundary.

## Are you trading real money?

No. The broker path is Alpaca PAPER only, disabled by default. Paper trading is
simulation and is not proof of live profitability.

## What if a provider dies?

Provider health is explicit; replay/offline mode remains available and is never
mislabelled as live. The UI exposes degraded state instead of an infinite
spinner or fabricated data.

## What did the ablations show?

The bounded research artifacts contain the actual smoke comparisons. Because the
dataset is synthetic and below the promotion threshold, ECHO does not claim an
empirical winner from them.
