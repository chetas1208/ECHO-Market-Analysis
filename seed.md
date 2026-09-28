# ECHO — Seed Context for Coding Agents

Use this document as the compact project seed when starting a new coding-agent session.

---

## Mission

Build **ECHO**, a real-time event-conditioned financial forecasting and simulation platform.

ECHO watches real-world events and live market activity simultaneously. It maps events through a causal economic knowledge graph, forecasts the remaining abnormal return distribution for affected stocks, freezes every prediction permanently, and compares those predictions against reality.

The goal is not to create a generic AI trader. The goal is to build an auditable system for **event → impact → forecast → verification → simulation**.

---

## Core Product Thesis

> Markets often price the company directly in the headline quickly, while information propagates unevenly across suppliers, customers, competitors, complements, commodities, geographies, technology dependencies, and risk-linked firms. ECHO models that propagation and forecasts the remaining abnormal return distribution.

---

## Non-Negotiable Product Rules

1. Do not build a multi-agent swarm.
2. Do not make a large LLM responsible for trading decisions.
3. Do not use raw future stock price as the primary forecast target.
4. Predict abnormal cumulative return distributions.
5. Every historical forecast must be immutable.
6. New information creates a new forecast vintage.
7. Risk controls must be deterministic.
8. The system must be allowed to abstain.
9. Live APIs must have replay/cached fallbacks.
10. Prefer a small, working system over a huge architecture.

---

## Required Inputs

### World intelligence

- World Monitor

### Live market data

- Massive as primary
- Alpaca as secondary/fallback

### Strategy / execution

- Conviction for strategy testing
- Alpaca for paper trading

### Financial events

- SEC / earnings / financial-news data where available

---

## Primary Data Flow

```text
World Monitor ──────────────┐
                           │
Massive ───────────────────┼──> Event Normalizer
                           │          │
Alpaca ────────────────────┤          ▼
                           │    Canonical Events
SEC/Earnings/Conviction ───┘          │
                                      ▼
                               Shock / Cause Engine
                                      │
                     ┌────────────────┴───────────────┐
                     ▼                                ▼
               Market Features                    ShockGraph
                     │                                │
                     └──────────────┬─────────────────┘
                                    ▼
                               Forecasting
                                    │
                  ┌─────────────────┼────────────────┐
                  ▼                 ▼                ▼
            Chronos-2-Small     LightGBM         GARCH/HAR
                  │                 │                │
                  └─────────────────┴────────────────┘
                                    ▼
                            Conformal Calibration
                                    │
                                    ▼
                            Prediction Ledger
                                    │
                    ┌───────────────┼──────────────┐
                    ▼               ▼              ▼
                   UI           Simulator      Conviction
                                                   │
                                                   ▼
                                                Alpaca
```

---

## Canonical Event

Use a normalized schema similar to:

```json
{
  "id": "evt_xxxx",
  "timestamp": "...",
  "source_type": "world|market|financial",
  "event_type": "supply_disruption",
  "entities": [],
  "companies": [],
  "locations": [],
  "economic_channels": {},
  "severity": 0.0,
  "novelty": 0.0,
  "confidence": 0.0,
  "source_refs": []
}
```

---

## Forecast Target

Primary target:

```text
CAR(i,e,h) = cumulative abnormal return
```

Remove broad market and sector movement.

Supported horizons:

- 1D
- 2D
- 5D
- 10D
- 20D
- visual/simulation support through 30 calendar days

Required forecast outputs:

- q10
- q50
- q90
- P(return > 0)

---

## Locked Model Stack

### ModernFinBERT

Use for:

- financial sentiment
- stance
- event importance
- text classification
- financial topic/tone

### Chronos-2-Small

Use for:

- market-only baseline
- probabilistic time-series context

Do not treat it as the alpha engine.

### LightGBM Quantile Regression

Use as the primary event-conditioned forecaster.

Features should include:

- event severity
- novelty
- corroboration
- graph exposure
- edge type
- return anomaly
- volume anomaly
- volatility anomaly
- market residual
- sector residual
- text features
- earnings surprise
- company characteristics

### GARCH / HAR-RV

Use for volatility/risk.

### Conformal Calibration

Use to calibrate prediction intervals.

### JEV

Optional.

Use only for fast action routing if API access exists:

- IGNORE
- WATCH
- FORECAST
- SIMULATE
- PAPER_TRADE

Do not use JEV as the forecaster.

---

## ShockGraph

Graph nodes:

- companies
- commodities
- geographies
- technologies
- industries
- infrastructure dependencies where useful

Graph edges:

- supplier
- customer
- competitor
- substitute
- complement
- commodity exposure
- geography
- regulation
- technology dependency
- risk similarity

Each edge requires:

- direction/sign
- weight
- confidence
- provenance

Initial universe: 50–100 liquid U.S. equities.

---

## Market Shock Detector

Compute:

- 1m / 5m / 15m returns
- return z-score
- volume z-score
- volatility z-score
- market residual
- sector residual
- optional spread/liquidity metrics

Emit a market shock only when the combination is unusual enough.

Also detect correlated/graph-connected cluster shocks.

---

## Cause Engine

For a market anomaly, rank nearby candidate causes by:

```text
CauseScore =
TemporalProximity
× EntityOverlap
× EconomicRelevance
× SourceConfidence
× GraphCompatibility
```

The engine may return `UNKNOWN` when evidence is insufficient.

---

## Prediction Ledger

Forecasts are append-only.

A forecast must record:

- ticker
- prediction timestamp
- data cutoff timestamp
- model version
- feature version
- graph snapshot
- event snapshot
- feature hash
- each horizon's q10/q50/q90
- P(up)

Never mutate historical forecasts.

Actual market observations are appended separately.

---

## UI Must Prove This Sequence

```text
EVENT
↓
WHAT CHANGED ECONOMICALLY
↓
WHO IS EXPOSED
↓
WHAT HAS ALREADY MOVED
↓
WHAT ECHO PREDICTS NEXT
↓
UNCERTAINTY
↓
FROZEN FORECAST
↓
WHAT ACTUALLY HAPPENED
↓
SIMULATED / PAPER TRADE RESULT
```

Primary screens:

- Dashboard
- Live Events
- Shock Investigator
- Event Detail
- ShockGraph
- Forecast
- Prediction Ledger
- Forecast vs Reality
- Trade Simulator
- Backtest / Conviction

---

## Risk Rules

Models cannot override:

- max position size
- max sector exposure
- correlated exposure limits
- minimum liquidity
- volatility-scaled sizing
- drawdown kill switch
- stop loss
- time stop
- max simultaneous positions

Risk management is deterministic software.

---

## Evaluation

Forecast metrics:

- MAE
- directional accuracy
- pinball loss
- interval coverage
- calibration

Trading metrics:

- total return
- Sharpe
- Sortino
- max drawdown
- hit rate
- turnover

Required baselines:

- random walk
- Chronos only
- sentiment only
- peer momentum
- sector momentum

Required ablations:

- remove graph
- remove event residual model
- remove market confirmation
- remove calibration
- remove text features

---

## Preferred Demo Scenarios

1. Taiwan earthquake → semiconductor supply chain
2. NVIDIA earnings → second-order beneficiaries
3. Strait of Hormuz disruption → energy / airlines / shipping
4. cloud outage → enterprise dependency network
5. oil supply disruption → producers / transport / industrial impact

---

## Implementation Bias

Prioritize:

- correctness
- auditability
- timestamp integrity
- fast local inference
- simple architecture
- reproducible replay
- measurable forecast quality

Avoid:

- unnecessary orchestration
- premature Rust rewrites
- Redpanda before it is needed
- large LLMs
- giant stock universes
- deep-learning complexity without evidence
- UI pages that do not support the core reasoning story

---

## Final Product Statement

> ECHO watches the world and the market simultaneously, estimates how new information should propagate through economically connected companies, issues timestamped probabilistic forecasts for that propagation, freezes every prediction permanently, and measures those forecasts against reality.
