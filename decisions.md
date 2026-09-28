# ECHO — Locked Technical and Product Decisions

This document records decisions that should not be reopened during implementation unless new empirical evidence clearly invalidates them.

---

## D-001 — Product Identity

**Decision:** ECHO is an event-conditioned forecasting and market intelligence system, not a generic stock prediction product.

**Reason:** Event propagation is the core research thesis and is easier to test, explain, and defend.

---

## D-002 — No Multi-Agent Swarm

**Decision:** Do not build a multi-agent financial swarm for the hackathon.

**Reason:** It is not required by the hackathon and adds latency, nondeterminism, cost, and debugging complexity.

**Allowed:** One externally described "ECHO Analyst" workflow with tool calls.

---

## D-003 — Primary Forecast Target

**Decision:** Predict abnormal cumulative returns, not raw future stock prices.

**Reason:** This removes broad market and sector movement from the primary target and better isolates event impact.

---

## D-004 — Probabilistic Forecasts

**Decision:** Every forecast must be a distribution, not a single point estimate.

**Required outputs:**

- q10
- q50
- q90
- probability of positive abnormal return

---

## D-005 — Immutable Prediction Ledger

**Decision:** Historical forecasts are append-only and cannot be rewritten.

**Reason:** Forecast integrity is central to evaluating whether ECHO actually predicted correctly.

**Rule:** New information creates a new forecast vintage.

---

## D-006 — Forecast Horizons

**Decision:** Support 1D, 2D, 5D, 10D, and 20D trading horizons, with visualization/simulation extending up to 30 calendar days.

**Reason:** These horizons align with event information diffusion and the product's short-to-medium-term strategy.

---

## D-007 — Primary Market Feed

**Decision:** Massive is the primary live market-data stream.

**Secondary:** Alpaca.

**Reason:** Massive is optimized for real-time market data, while Alpaca is also needed for paper execution.

---

## D-008 — World Event Feed

**Decision:** World Monitor is the primary external-world intelligence source.

**Integration:** API/MCP/structured interface, not a fork of its full application.

---

## D-009 — Alpaca Role

**Decision:** Alpaca is used for:

- secondary market-data validation
- paper execution
- portfolio/account state

Do not make it the only market source.

---

## D-010 — Conviction Role

**Decision:** Conviction is used for strategy formulation, testing, and hackathon compliance.

It is not the sole data layer or the entire ECHO backend.

---

## D-011 — Model Stack

**Decision:** Use small, specialized models rather than one large LLM.

Locked stack:

- ModernFinBERT — financial text understanding
- Chronos-2-Small — market-only time-series baseline
- LightGBM quantile models — primary event-conditioned forecast
- GARCH/HAR-RV — volatility
- conformal calibration — uncertainty
- JEV — optional routing only

---

## D-012 — JEV

**Decision:** JEV is optional and only used if programmatic API access exists.

**Allowed uses:**

- IGNORE / WATCH / FORECAST / PAPER_TRADE routing
- horizon preference
- sufficiency / escalation decisions

**Forbidden use:** direct stock-price forecasting.

---

## D-013 — Large Language Models

**Decision:** No high-parameter LLM belongs in the critical trading path.

A small local language model may be used only for user-facing explanations if necessary.

---

## D-014 — Local Model Budget

**Decision:** Keep the model package lightweight and practical for local execution.

Target:

- small checkpoints
- quantization where appropriate
- lazy loading
- fast CPU/GPU inference

Do not optimize the entire application around an arbitrary total-RAM number until profiling exists.

---

## D-015 — ShockGraph

**Decision:** The graph is causal/economic, not merely correlational.

Valid edge classes include:

- supplier
- customer
- competitor
- substitute
- complement
- commodity exposure
- geographic exposure
- regulatory exposure
- technology dependency
- risk similarity

Each edge requires:

- sign
- weight
- confidence
- provenance

---

## D-016 — Bidirectional Intelligence

**Decision:** ECHO must support both:

- world event → market impact
- market anomaly → likely world/financial cause

This is a core differentiator.

---

## D-017 — Market Shock Detection

**Decision:** Detect market shocks using multiple features, not price change alone.

Required signals:

- return anomaly
- volume anomaly
- volatility anomaly
- sector residual
- market residual
- optional spread/liquidity change

---

## D-018 — Cause Attribution

**Decision:** Cause matching is probabilistic and may return "unknown".

Never force an explanation when evidence is insufficient.

---

## D-019 — Abstention

**Decision:** Abstention is a first-class system action.

Possible decisions:

- IGNORE
- WATCH
- FORECAST
- SIMULATE
- PAPER_TRADE

The system should prefer no trade over low-confidence trade.

---

## D-020 — Risk Engine

**Decision:** Risk is deterministic.

Models cannot override:

- max position size
- max exposure
- drawdown kill switch
- stop loss
- time stop
- minimum liquidity
- maximum simultaneous trades

---

## D-021 — Time-Series Foundation Model Role

**Decision:** Chronos-2-Small is a market baseline, not the alpha engine.

**Reason:** Time-series foundation models can provide useful baseline forecasts, but evidence for consistent stock-return alpha is limited.

---

## D-022 — Primary Alpha Model

**Decision:** LightGBM quantile regression is the main event-conditioned forecasting model for the hackathon.

**Reason:** ECHO's strongest features are structured, mixed-type, and tabular.

---

## D-023 — Uncertainty

**Decision:** Use conformal calibration over recent out-of-sample residuals.

Forecast intervals must be evaluated for actual empirical coverage.

---

## D-024 — Storage

**Decision:** PostgreSQL is the primary store.

TimescaleDB extension is optional if easy to deploy.

---

## D-025 — Streaming

**Decision:** Do not introduce Redpanda during the hackathon unless the simpler path becomes insufficient.

Hackathon default:

- asyncio queues or Redis Streams

Post-hackathon:

- Redpanda

---

## D-026 — Rust

**Decision:** No Rust rewrite until profiling proves Python is the bottleneck.

Python is sufficient for the hackathon's initial 50–100 asset universe.

---

## D-027 — Stock Universe

**Decision:** Start with 50–100 highly liquid, shock-sensitive equities.

Prioritize:

- semiconductors
- hyperscalers
- energy
- airlines
- shipping/logistics
- defense
- cybersecurity
- industrials
- banks
- commodity-linked equities

---

## D-028 — Backtesting

**Decision:** Backtesting must preserve historical information boundaries.

Required:

- timestamped inputs
- no future data leakage
- transaction costs
- event replay
- frozen graph/data snapshots where possible

---

## D-029 — Baselines and Ablations

**Decision:** ECHO is not considered validated without comparisons.

Required baselines:

- random walk
- Chronos-only
- sentiment-only
- peer momentum
- sector momentum

Required ablations:

- no graph
- no event model
- no market confirmation
- no calibration
- no text features

---

## D-030 — UI Philosophy

**Decision:** The UI should prove the reasoning chain visually.

Primary sequence:

```text
Event
→ economic channel
→ affected company
→ current reaction
→ predicted distribution
→ immutable forecast
→ actual path
→ simulated/paper trade
```

Do not build unnecessary dashboard pages that do not contribute to this story.

---

## D-031 — Demo Reliability

**Decision:** The demo must work even if a live API is down.

Maintain:

- cached events
- frozen market data
- replayable historical scenarios

---

## D-032 — Success Definition

ECHO succeeds if it demonstrates all of the following:

1. real event ingestion
2. real market ingestion
3. causal/economic exposure mapping
4. probabilistic multi-horizon forecast
5. immutable prediction storage
6. prediction-vs-reality verification
7. trade simulation
8. Conviction validation
9. paper execution capability
10. defensible performance evaluation
