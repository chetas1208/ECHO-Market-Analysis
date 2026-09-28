# ECHO resource and architecture lock

Status: **LOCKED**  
Version: `ECHO 0.2.0-dev`  
Scope: post-hackathon foundation; decisions below are the default engineering boundary

## Principle

ECHO is a financial event system with small specialized models inside it. The system brain is the
combination of canonical events, structured economic relationships, market statistics, calibrated
forecasts, and deterministic risk controls. No general-purpose LLM is in the trading path.

## Locked architecture

```text
World Monitor / Massive / Alpaca / SEC or earnings sources
                    |
             asyncio provider adapters
                    |
             canonical event schemas
                    |
      Polars market features + event intelligence
                    |
      PostgreSQL graph truth + bounded graph propagation
                    |
       cause engine -> forecast fusion -> ledger
                    |
       simulator / backtester -> deterministic risk gate
                    |
              Alpaca PAPER only -> Next.js UI
```

PostgreSQL is the source of truth for events, market observations, graph snapshots, forecast
vintages, actuals, simulations, execution records, and audits. NetworkX remains an approved
research/offline option for small snapshots; the current runtime uses ECHO's bounded deterministic
propagation implementation and does not add an unused graph dependency.

## Technology decisions

| Area | Locked choice | Repository status |
| --- | --- | --- |
| Frontend | Next.js, React, TypeScript | ACTIVE |
| Charts | Existing SVG/chart components; Lightweight Charts may be added for richer replay | OPTIONAL |
| Graph UI | Existing curated graph workspace; React Flow/Cytoscape only if interaction needs it | OPTIONAL |
| API | FastAPI + Pydantic v2 | ACTIVE |
| Runtime | Python 3.12 | ACTIVE |
| Database | PostgreSQL 16+ | ACTIVE |
| ORM/driver | SQLAlchemy async + asyncpg | ACTIVE |
| Schema | Alembic | ACTIVE |
| Market processing | Polars + NumPy | ACTIVE |
| Graph truth | PostgreSQL snapshots | ACTIVE |
| Graph compute | Bounded deterministic propagation; optional local AURE store with explicit NetworkX fallback | ACTIVE / OPTIONAL |
| Text feature | ModernFinBERT, lazy and local-only | OPTIONAL |
| Time-series baseline | Chronos-2-Small, local-only | OPTIONAL; unavailable in clean runtime |
| Event alpha | LightGBM quantile models | OPTIONAL; fallback artifact is active |
| Volatility | HAR-RV; GARCH may be evaluated later | ACTIVE / OPTIONAL |
| Calibration | Conformal prediction | ACTIVE |
| Routing | Deterministic decision gate; JEV only with verified API access | ACTIVE / OPTIONAL |
| Execution | Replay and Alpaca PAPER adapters | ACTIVE; live prohibited |
| Research data | Parquet + ZSTD for large offline exports | DEFERRED until dataset volume requires it |
| Internal messaging | Bounded `asyncio.Queue` | ACTIVE |
| Durable messaging | Redpanda only after measured need | DEFERRED |
| Infrastructure | Docker Compose/local host; managed PostgreSQL later | ACTIVE / FUTURE |
| Metrics | Prometheus-compatible exposition | ACTIVE |

## Model boundaries

### ModernFinBERT

Use only for financial text features such as sentiment, stance, topic, and relevance. It must not
choose trades, reason over geopolitics, or forecast returns. Load lazily and use pinned local files;
the analyzer may be disabled without blocking ingestion.

### Chronos-2-Small

Use as the market-only counterfactual baseline. It is not the alpha generator. Do not claim a
Chronos benchmark until the checkpoint and package are actually present.

### LightGBM

Use structured event/graph/market features for q10/q50/q90 forecasts across 1D/2D/5D/10D/20D.
The checked-in linear pinball bundle is the current deterministic fallback; an optional LightGBM
backend must be evaluated, hashed, registered, and explicitly promoted.

### HAR-RV/GARCH and conformal calibration

Volatility estimates support risk and sizing, not directional alpha. Conformal calibration governs
interval coverage claims. Risk gates remain deterministic and cannot be overridden by model output.

### LLMs and JEV

No large LLM, multi-agent swarm, or explanation model is required. A small explanation model is
optional and may only turn structured evidence into text. JEV is an optional decision router for
`IGNORE`, `WATCH`, `FORECAST`, `SIMULATE`, and `PAPER_TRADE`; it is never a price forecaster.

## Data and storage policy

- Hot: current bars, queues, provider health, and active model state.
- Warm: normalized bars, event evidence, features, and reproducible research inputs.
- Archive: prediction ledger, graph snapshots, trades, fills, reconciliation, and audit records.
- Large offline datasets may use Parquet/ZSTD; live PostgreSQL rows are not manually compressed.
- Every derived dataset/model records provider/source, cutoff/date range, generation version, config
  hash, and content hash.
- A demo must work offline from deterministic replay artifacts; it must not require Wi-Fi or secrets.

## Processing funnel

```text
raw observations -> cheap filters -> anomalies/events -> graph exposure
                 -> forecast candidates -> risk gate -> zero to three paper actions
```

Do not run expensive models on every observation. FinBERT runs on eligible new financial text;
graph propagation runs on meaningful events; LightGBM runs on candidate event/company pairs; Chronos
runs only for serious forecast candidates; volatility is cached and refreshed periodically.

## Resource envelope

### Minimum

- 6–8 modern CPU cores
- 16 GB RAM
- 20–40 GB free disk
- no GPU

### Comfortable

- 8–12 CPU cores
- 32 GB RAM
- 100+ GB NVMe
- optional 6–8 GB NVIDIA GPU

The entire local stack may reasonably use 2–6 GB RAM. Optional model workers may use 500 MB–1 GB
each. Extreme-light mode keeps Chronos non-resident, leaves Qwen out, and uses deterministic
Polars/LightGBM/HAR/graph components.

## Deployment boundary

Current local deployment is PostgreSQL plus FastAPI plus Next.js. Replay mode is offline-safe.
Production can move the frontend to Vercel and the backend to a managed platform, but provider
credentials, database backups, health probes, and paper-only execution controls must remain explicit.
Kubernetes, Spark, Ray, Neo4j, Kafka, Redis, vector databases, MongoDB, ClickHouse, LangChain,
CrewAI, AutoGen, and large agent swarms are not part of the locked foundation. They require a
measured problem and a separate ADR.

## Explicitly deferred

- Neo4j or another remote graph database. AURE is a local, opt-in graph-store integration and is not
  required by replay mode.
- Redpanda/Kafka/Redis process messaging.
- Kubernetes and distributed compute frameworks.
- GNNs, options, international markets, and a large universe.
- Mandatory LLM reasoning or online model learning.
- Vector database; use PostgreSQL/pgvector only if semantic search proves necessary.
- Parquet research storage until current database/data-volume measurements justify it.

## Verification rule

This document is a resource boundary, not proof that every optional component is installed. Runtime
claims must be supported by the model registry, benchmark artifacts, health endpoints, and release
audit. Optional dependencies are installed only through explicit backend dependency groups; model
weights are never committed to Git or downloaded at request time.
