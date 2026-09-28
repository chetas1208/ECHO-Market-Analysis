# Cause Engine

Day 5 adds deterministic bidirectional evidence ranking. It does not prove
causality, generate explanations with an LLM, forecast returns, or emit trading
actions.

## Inputs and information modes

`CauseEngine.investigate_market_shock()` consumes a canonical `MARKET` event of
type `market_shock`, candidate canonical WORLD/FINANCIAL events, and a declared
ShockGraph snapshot. Candidate retrieval is bounded to a six-hour lookback by
default, with zero realtime lookahead and a 24-hour retrospective lookahead.

`REALTIME` excludes candidate events and graph snapshots created after
`data_cutoff_at`, and excludes canonical events ingested after that cutoff.
`RETROSPECTIVE` can inspect the configured post-shock window, but evidence is
marked `post_shock_evidence` in the candidate evidence payload.

Event occurrence is the canonical event `timestamp`; source publication times
remain inside source evidence and are not substituted for occurrence time.

## Candidate scoring

For candidate event `e` and market shock `s`:

```text
CauseScore =
    0.20 * TemporalScore
  + 0.15 * EntityScore
  + 0.20 * EconomicRelevanceScore
  + 0.20 * GraphCompatibilityScore
  + 0.15 * MarketCompatibilityScore
  + 0.10 * SourceConfidenceScore
```

Weights are centralized in `CauseConfig`, normalized before scoring, hashed, and
stored with every investigation. Temporal score is:

```text
exp(-abs(event_timestamp - shock_timestamp) / temporal_tau)
```

with a default one-hour decay constant. Entity score rewards direct company or
canonical entity matches. Economic score uses the absolute ShockGraph exposure
times exposure confidence. Graph score additionally applies directional
agreement between expected exposure and observed shock direction. Market score
compares observed market-shock directions for exposed peers inside a bounded
30-minute pattern window. Source score combines event confidence,
corroboration, and independent source count.

All components are stored separately. A CauseScore is an evidence compatibility
score, not a causal probability.

## Result states

- `IDENTIFIED`: top score is at least `0.55` and exceeds the runner-up by more
  than `0.08`.
- `AMBIGUOUS`: top score passes the threshold but the runner-up is within `0.08`.
- `UNKNOWN`: no candidate passes the threshold or no candidate is visible.

Every candidate retains structured temporal, channel, graph, market-pattern,
and source-quality evidence plus the selected graph paths.

## World to market response

`analyze_world_event()` propagates event channels through ShockGraph, then joins
visible market shocks by symbol. It returns exposure, confidence, actual
residual z-score, response state, and graph paths. Response states are:

`NOT_OBSERVED`, `OPPOSITE`, `UNCONFIRMED`, `PARTIAL`, `CONFIRMED`, and
`OVERREACTING`. They compare normalized residual magnitude and direction against
graph exposure; they are not forecasts.

## Cluster detection

Cluster detection uses structured memberships from sector, technology, and
geography graph relationships. It requires at least three abnormal members,
absolute residual z-score at least `1.0`, synchronization within ten minutes,
and directional majority. Strength combines normalized average residual,
directional agreement, and synchronization. Elevated volume confirmation is
reported separately. Price correlation is not used to create membership.

Clusters are immutable records with stable content-derived IDs and can be
retrieved through the cluster API.

Investigation logs include candidate-retrieval and end-to-end duration fields
so replay performance can be measured without changing the persisted evidence.

## Persistence and APIs

`cause_investigations`, `cause_candidates`, and `cluster_shocks` are append-only
PostgreSQL tables protected by always-enabled mutation triggers. Investigations
store the shock event, graph snapshot, mode, cutoff, engine/config versions,
config hash, status, component candidates, and evidence.

Endpoints:

- `POST /api/v1/investigations/market-shock/{event_id}`
- `GET /api/v1/investigations/{investigation_id}`
- `GET /api/v1/events/{event_id}/market-impact`
- `GET /api/v1/market/clusters`

The existing Graph tab contains the Shock Investigator sub-view. It shows
identified, ambiguous, and unknown states intentionally; it does not add a
primary tab or display BUY/SELL language.

## Limitations

The initial market-pattern join consumes canonical market-shock events rather
than a full intraday bar-window model. Source publication versus occurrence
uncertainty is preserved but not probabilistically calibrated. Cluster groups
are structured graph memberships, not learned causal communities. Day 6
forecasting is not implemented.
