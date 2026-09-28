# ECHO — Locked Project Plan

## 1. Project Definition

**ECHO** is a real-time event-conditioned financial forecasting and simulation platform.

It watches both:

1. **The real world** through World Monitor and structured financial/news sources.
2. **The market** through live stock-market feeds such as Massive and Alpaca.

ECHO detects shocks from either direction, connects them through an economic knowledge graph, estimates which listed companies are exposed, forecasts event-conditioned abnormal returns across multiple horizons, freezes every prediction permanently, and then compares those forecasts with what actually happens.

The system is designed to answer:

> What happened, what probably caused it, which companies should be affected, how much of that information has already been priced in, and what is the probability distribution of the remaining move?

---

## 2. Locked Product Thesis

ECHO is **not**:

- a generic AI stock picker
- an LLM trading chatbot
- a multi-agent swarm
- a raw sentiment bot
- a single-line 30-day price predictor
- an HFT system

ECHO **is**:

- an event intelligence system
- a market anomaly detector
- a causal propagation engine
- a probabilistic forecaster
- an immutable prediction ledger
- a trade simulator
- a Conviction-compatible strategy research system

The core hypothesis is:

> Markets often price the company directly in the headline quickly, but economically connected companies can absorb the same information unevenly. ECHO models that propagation and forecasts the remaining abnormal return distribution.

---

## 3. Core User Experience

The primary user flow is:

1. A world or market event is detected.
2. ECHO normalizes it into a canonical event.
3. The knowledge graph identifies affected companies and economic channels.
4. ECHO calculates the current market reaction.
5. The forecasting stack estimates abnormal return distributions for multiple horizons.
6. ECHO recommends a horizon based on expected risk-adjusted information decay.
7. The forecast is permanently frozen as a new prediction vintage.
8. Actual market observations are appended over time.
9. The UI shows **prediction vs. reality**.
10. The trade simulator shows how the predicted strategy would have performed.
11. Conviction is used to validate the strategy and Alpaca can execute paper trades.

---

## 4. Core Product Screens

### 4.1 Dashboard

Shows:

- active world events
- active market anomalies
- forecast opportunities
- recent prediction performance
- paper positions
- strategy metrics

### 4.2 Live Events

World Monitor and financial-event feed with:

- event type
- source
- timestamp
- severity
- novelty
- corroboration
- confidence

### 4.3 Market Shock Investigator

For a detected market anomaly:

- ticker
- return anomaly
- volume z-score
- volatility z-score
- sector-relative move
- probable causes
- evidence
- related graph nodes
- underreacting / overreacting assets

### 4.4 Event Detail

Shows:

- event summary
- sources
- economic channels
- affected geographies
- affected companies
- historical analogues
- event confidence

### 4.5 ShockGraph

Visual graph of:

- suppliers
- customers
- competitors
- complements
- commodity exposure
- geographic exposure
- regulatory exposure
- technology dependencies
- risk-similarity links

Each edge contains:

- relationship type
- sign
- weight
- confidence

### 4.6 Forecast View

For a selected company:

- historical chart up to one month before the forecast
- live/current actual price
- prediction starting at forecast timestamp
- 1D / 2D / 5D / 10D / 20D / 30D horizons
- q10 / q50 / q90 forecast bands
- probability of positive abnormal return
- recommended horizon
- information half-life

### 4.7 Prediction Ledger

Every forecast is immutable.

Each forecast stores:

- model version
- graph snapshot
- feature version
- data cutoff timestamp
- event snapshot
- prediction timestamp
- all horizon forecasts
- uncertainty bands

New information creates a **new forecast vintage**, never an overwrite.

### 4.8 Forecast vs Reality

For any historical prediction:

- original frozen forecast
- actual subsequent market path
- directional correctness
- forecast error
- interval coverage
- calibration
- simulated P&L

### 4.9 Trade Simulator

Simulates:

- long / short decision
- entry
- exit horizon
- hedge
- position size
- stop / time stop
- predicted return
- realized return
- trade confidence

### 4.10 Backtest / Conviction

Shows:

- total return
- Sharpe
- Sortino
- max drawdown
- hit rate
- turnover
- benchmark comparison
- baseline comparison
- ablation studies
- event replay

---

## 5. System Architecture

```text
WORLD MONITOR ──────────────┐
                           │
MASSIVE MARKET STREAM ─────┼────> EVENT NORMALIZER
                           │              │
ALPACA STREAM ─────────────┤              ▼
                           │        CANONICAL EVENTS
SEC / EARNINGS / CONVICTION┘              │
                                          ▼
                                 SHOCK / CAUSE ENGINE
                                          │
                         ┌────────────────┴───────────────┐
                         ▼                                ▼
                 MARKET FEATURES                     ShockGraph
                 price/volume/vol                causal exposures
                         │                                │
                         └──────────────┬─────────────────┘
                                        ▼
                              FORECASTING STACK
                                        │
                       ┌────────────────┼───────────────┐
                       ▼                ▼               ▼
                Chronos-2-Small     LightGBM        GARCH/HAR
                market baseline    event residual   volatility
                       └────────────────┬───────────────┘
                                        ▼
                              FORECAST FUSION
                                        │
                                        ▼
                              CONFORMAL CALIBRATION
                                        │
                                        ▼
                              PREDICTION LEDGER
                                        │
                           ┌────────────┼────────────┐
                           ▼            ▼            ▼
                        UI          SIMULATOR     CONVICTION
                                                   │
                                                   ▼
                                                ALPACA
                                             PAPER EXECUTION
```

---

## 6. Data Sources

### Primary

- **World Monitor** — real-world shock intelligence
- **Massive** — primary real-time market feed
- **Alpaca** — secondary live market feed and paper execution
- **Conviction** — strategy construction / validation
- **SEC / earnings sources** — event fundamentals

### Optional / secondary

- company news
- macro calendar
- commodity prices
- sector ETFs
- VIX
- historical event datasets

---

## 7. Canonical Event Schema

```json
{
  "id": "evt_xxxx",
  "timestamp": "...",
  "source_type": "world|market|financial",
  "event_type": "supply_disruption",
  "entities": [],
  "companies": [],
  "locations": [],
  "economic_channels": {
    "oil_supply": -0.82,
    "shipping_cost": 0.77
  },
  "severity": 0.82,
  "novelty": 0.74,
  "confidence": 0.91,
  "source_refs": []
}
```

All downstream services consume this normalized format.

---

## 8. Forecasting Target

Do not predict raw prices as the primary target.

Predict **future abnormal cumulative return**:

```text
CAR(i,e,h) = sum[r_i - beta_market*r_market - beta_sector*r_sector]
```

Supported horizons:

- 1 trading day
- 2 trading days
- 5 trading days
- 10 trading days
- 20 trading days
- up to 30 calendar days for visualization / simulation

The product may render an implied price path, but the model target remains abnormal return.

---

## 9. Forecasting Stack

### 9.1 ModernFinBERT

Purpose:

- financial sentiment
- stance
- topic
- event importance
- management tone
- headline impact

Not responsible for final trading decisions.

### 9.2 Chronos-2-Small

Purpose:

- market-only baseline forecast
- probabilistic time-series forecast
- lightweight local inference

### 9.3 LightGBM Quantile Models

Primary event-conditioned alpha model.

Inputs include:

- event severity
- novelty
- corroboration
- graph exposure
- relationship type
- market reaction
- volume anomaly
- volatility anomaly
- sector residual
- financial sentiment
- earnings surprise
- company characteristics

Outputs:

- q10
- q50
- q90

for each horizon.

### 9.4 GARCH / HAR-RV

Purpose:

- volatility estimation
- risk normalization
- horizon scoring

### 9.5 Conformal Calibration

Purpose:

- calibrated uncertainty intervals
- coverage guarantees based on recent out-of-sample residuals

### 9.6 JEV — Optional

Use only as a fast decision router if programmatic API access exists.

Possible decisions:

- IGNORE
- WATCH
- FORECAST
- PAPER_TRADE
- ESCALATE

Do not use JEV as the price forecaster.

---

## 10. Horizon Selection

For each event class, estimate an information half-life.

A simple impact-decay model:

```text
Impact(h) = Impact_inf * (1 - exp(-h / tau_class))
```

Then select the horizon maximizing expected risk-adjusted opportunity:

```text
Score(h) = abs(E[CAR_h]) / sigma_h - costs_h
```

Recommended horizon:

```text
h* = argmax Score(h)
```

---

## 11. Market Shock Detection

Per asset compute:

- 1m / 5m / 15m return
- return z-score
- volume z-score
- volatility z-score
- spread change
- sector residual
- market residual

A market shock is emitted when a combination of these exceeds calibrated thresholds.

Also detect **cluster shocks** when economically connected stocks move together.

---

## 12. Cause Matching

When a market shock occurs:

1. collect nearby world/news/SEC events
2. score candidate causes
3. rank by:
   - temporal proximity
   - entity overlap
   - economic relevance
   - source confidence
   - ShockGraph compatibility

The system should always preserve uncertainty and may return:

- likely cause
- multiple plausible causes
- unknown cause

---

## 13. Risk and Execution

Risk controls remain deterministic.

LLMs or models cannot override:

- max position size
- max sector exposure
- max correlated exposure
- minimum liquidity
- volatility-scaled sizing
- max drawdown kill switch
- stop loss
- time stop
- max simultaneous trades

AI interprets information.

Software controls capital.

---

## 14. Prediction Ledger Requirements

Each forecast must be append-only.

Never mutate historical forecasts.

Required entities:

### forecast_run

- id
- ticker
- created_at
- data_cutoff_at
- model_version
- feature_version
- event_snapshot_id
- graph_snapshot_id
- feature_hash

### forecast_point

- forecast_id
- horizon
- target_timestamp
- q10_return
- q50_return
- q90_return
- probability_up

### market_observation

- ticker
- timestamp
- actual_price
- actual_return

---

## 15. Evaluation

Forecast quality:

- MAE
- directional accuracy
- pinball loss
- interval coverage
- probability calibration

Trading quality:

- total return
- Sharpe
- Sortino
- max drawdown
- hit rate
- turnover

Mandatory baselines:

1. random walk / no-event baseline
2. market-only Chronos forecast
3. sentiment-only strategy
4. simple peer momentum
5. sector momentum
6. full ECHO

Mandatory ablations:

- without graph
- without event residual model
- without market confirmation
- without calibration
- without text features

---

## 16. Hackathon Build Scope

### P0 — must work

- World Monitor ingestion
- Massive ingestion
- Alpaca integration
- canonical event schema
- market shock detector
- 50–100 company ShockGraph
- event/market cause matcher
- Chronos baseline
- LightGBM quantile model
- volatility model
- prediction ledger
- forecast vs reality UI
- trade simulator
- Conviction strategy
- event replay

### P1 — strong differentiators

- cluster shock detection
- historical analog retrieval
- REM earnings pipeline
- JEV routing
- confidence calibration dashboard
- ablation dashboard
- long/short hedged simulations

### P2 — defer

- Redpanda
- Rust rewrite
- thousands of equities
- graph neural networks
- options
- international execution
- multi-agent swarm
- custom large language models

---

## 17. Technical Stack

### Backend

- Python 3.12+
- FastAPI
- asyncio
- Polars
- LightGBM
- NetworkX initially
- statsmodels / arch
- PyTorch only where required

### Streaming

Hackathon:

- asyncio queue or Redis Streams

Post-hackathon:

- Redpanda

### Storage

- PostgreSQL
- TimescaleDB extension if convenient

### Frontend

- Next.js
- React
- React Flow or Cytoscape
- TradingView Lightweight Charts
- MapLibre / deck.gl

### Execution

- Alpaca paper trading

---

## 18. Core Demo Story

The demo should show one complete chain:

```text
REAL EVENT
    ↓
ECHO DETECTS IT
    ↓
ECONOMIC CHANNELS
    ↓
AFFECTED COMPANIES
    ↓
EXPECTED VS OBSERVED REACTION
    ↓
FORECAST DISTRIBUTION
    ↓
FROZEN PREDICTION
    ↓
SIMULATED TRADE
    ↓
ACTUAL OUTCOME
```

Preferred demo scenarios:

- Taiwan earthquake → semiconductor network
- NVIDIA earnings → second-order infrastructure beneficiaries
- Strait of Hormuz disruption → energy / airlines / shipping
- major cloud outage → enterprise dependency graph
- oil supply disruption → cross-sector impact

---

## 19. Final Product Statement

> **ECHO watches the world and the market simultaneously, estimates how new information should propagate through economically connected companies, issues timestamped probabilistic forecasts for that propagation, freezes every prediction permanently, and measures those forecasts against reality.**

This plan is now locked unless empirical results force a change.
