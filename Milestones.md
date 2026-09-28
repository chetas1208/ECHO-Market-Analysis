# ECHO — 10-Day Milestone Plan

One milestone per day. Each day ends with a concrete artifact that can be tested independently.

---

## Day 1 — Foundation and Contracts

### Goal
Lock the data contracts, repository structure, and minimal end-to-end skeleton.

### Build

- repository structure
- environment configuration
- FastAPI service
- PostgreSQL schema
- canonical event schema
- forecast ledger schema
- market observation schema
- base frontend shell
- logging and error handling

### Deliverable

A running system where a mocked world event can be inserted, stored, fetched through API, and displayed in the UI.

### Exit Criteria

- canonical event persists correctly
- immutable forecast tables exist
- frontend can render one event
- all services launch locally

---

## Day 2 — Real-Time Market Feed

### Goal
Connect to real market data and detect basic anomalies.

### Build

- Massive WebSocket integration
- Alpaca market-data fallback
- real-time 1m / 5m / 15m bars
- Polars feature pipeline
- return z-score
- volume z-score
- volatility z-score
- market/sector residuals
- market shock event generation

### Deliverable

Live market panel showing tracked tickers and emitted `MARKET_SHOCK` events.

### Exit Criteria

- live data remains connected
- reconnect logic works
- shock events are reproducible
- market events enter canonical event pipeline

---

## Day 3 — World Monitor + Event Intelligence

### Goal
Bring real-world shocks into the same event system.

### Build

- World Monitor integration
- event normalization
- source attribution
- severity
- novelty
- corroboration
- confidence
- economic channel extraction
- ModernFinBERT integration

### Deliverable

World events and market shocks appear in one unified feed.

### Exit Criteria

- World Monitor events ingest correctly
- events are normalized
- structured channels are stored
- raw sources remain traceable

---

## Day 4 — ShockGraph

### Goal
Map events to affected companies through economic relationships.

### Build

- initial 50–100 stock universe
- graph nodes and edges
- supplier/customer relationships
- competitor/complement relationships
- commodity/geography/technology/risk edges
- signed edge direction
- exposure propagation formula
- graph snapshot versioning

### Deliverable

Interactive graph where selecting an event returns ranked affected companies with exposure scores.

### Exit Criteria

- graph responses are deterministic
- edge provenance is stored
- graph snapshot IDs can be attached to forecasts

---

## Day 5 — Cause Engine + Bidirectional Reasoning

### Goal
Support both world→market and market→world reasoning.

### Build

- event→company propagation
- market shock→candidate cause search
- temporal proximity scoring
- entity overlap scoring
- economic relevance scoring
- graph compatibility scoring
- cluster shock detection
- cause confidence

### Deliverable

Shock Investigator page showing probable causes for a market move and affected assets for a world event.

### Exit Criteria

- market shock can retrieve candidate causes
- unknown cause is an allowed result
- world event can rank affected stocks

---

## Day 6 — Forecasting Engine

### Goal
Produce event-conditioned probabilistic return forecasts.

### Build

- Chronos-2-Small market baseline
- LightGBM feature dataset
- LightGBM quantile models
- 1D / 2D / 5D / 10D / 20D horizons
- GARCH/HAR volatility estimate
- forecast fusion
- initial horizon recommendation

### Deliverable

For a selected event-stock pair, return q10/q50/q90 abnormal return forecasts across all horizons.

### Exit Criteria

- forecasts run locally
- model latency is acceptable
- outputs are deterministic under fixed inputs
- raw prices are not the primary target

---

## Day 7 — Immutable Prediction Ledger + Simulator

### Goal
Make every prediction auditable and impossible to rewrite.

### Build

- append-only forecast creation
- model/version hashes
- graph snapshot reference
- data cutoff timestamp
- feature hash
- actual observation appending
- forecast-vs-reality chart
- simulated trade records
- paper position state

### Deliverable

Prediction Ledger page where previous predictions remain unchanged while actual observations accumulate.

### Exit Criteria

- historical forecasts cannot be updated via application code
- new information produces a new forecast vintage
- actual observations appear alongside old forecasts

---

## Day 8 — Calibration, Risk, and Decision Gate

### Goal
Turn forecasts into robust decisions without letting models control risk.

### Build

- conformal calibration
- interval coverage reporting
- trade confidence
- deterministic risk controls
- position sizing
- max exposure rules
- stop / time stop
- abstention logic
- optional JEV router if API access is confirmed

### Deliverable

System outputs one of:

- IGNORE
- WATCH
- FORECAST
- SIMULATE
- PAPER_TRADE

with reasons and confidence.

### Exit Criteria

- risk rules cannot be overridden by model output
- low-confidence signals abstain
- JEV remains optional

---

## Day 9 — Conviction, Paper Execution, Backtesting

### Goal
Validate the strategy under the hackathon's actual scoring conditions.

### Build

- Conviction strategy implementation
- Alpaca paper execution
- historical event replay
- transaction costs
- baseline strategies
- ablation tests
- Sharpe / Sortino / drawdown / hit rate
- replay timeline

### Deliverable

Backtest dashboard comparing full ECHO against baselines and ablations.

### Exit Criteria

- no future data leaks
- historical predictions use timestamped inputs
- paper trades are reproducible
- strategy metrics are generated automatically

---

## Day 10 — Product Polish + Winning Demo

### Goal
Turn the working system into a clear 3–5 minute judge demo.

### Build

- final dashboard polish
- live event feed
- ShockGraph visualization
- forecast chart
- prediction-vs-reality mode
- trade simulator
- event replay
- failure / abstention examples
- demo dataset fallback
- pitch narrative

### Deliverable

A complete demo showing:

```text
Event
→ economic impact
→ exposed companies
→ expected vs observed reaction
→ probabilistic forecast
→ frozen prediction
→ simulated/paper trade
→ actual result
```

### Exit Criteria

- demo survives API outage using cached replay data
- one-click local startup
- one polished event story
- all critical flows work without manual database editing
- project README and architecture diagram are complete

---

# Post-Day-10 Work

Only after the hackathon-critical build is stable:

- Redpanda
- Rust optimization
- larger universe
- deeper supply-chain data
- dynamic graph learning
- GNN research
- options
- international markets
- automated model retraining
- production observability
