# ECHO codebase summary and E2E evidence

Run: `20260921T020222Z`
Generated: `2026-09-21T02:05:52.008016+00:00`

## Product

ECHO is an event-conditioned market intelligence terminal. It ingests world events and market observations, normalizes them into canonical domain records, propagates event channels through a curated ShockGraph, produces calibrated abnormal-return forecasts, records immutable prediction vintages, runs deterministic strategy/backtest simulations, and permits only replay or Alpaca PAPER execution behind risk gates.

The UI surface is Dashboard, Events, Graph, Forecasts, Strategy, and Operations. The browser-visible mode is explicitly replay/offline/live-aware; synthetic replay data is not represented as live data.

## Backend

The backend is FastAPI + Pydantic v2 + SQLAlchemy async + asyncpg + Alembic, running on Python 3.12+. It contains 173 Python application files, 9 migrations, and 73 test modules.

Major areas:

- `app/api`: health/readiness, events, market, world, graph, cause, forecasting, ledger, backtests, execution, operations, and configuration status.
- `app/market`: bounded ingest queue, replay provider, Massive WebSocket adapter, Alpaca data adapter, feature/z-score/shock detection, failover supervision, and market persistence.
- `app/world`: replay provider, World Monitor REST/MCP adapter, deduplication, normalization, severity/novelty/corroboration/confidence scoring, and optional local text analysis.
- `app/graph`: curated graph seed, PostgreSQL snapshots, bounded deterministic propagation, AURE capability resolution, and explicit fallback status.
- `app/cause`: bidirectional cause/market-impact investigation, candidate ranking, graph paths, cluster detection, and UNKNOWN/degraded states.
- `app/forecasting`: feature assembly, OOD checks, quantile forecast artifacts, conformal/isotonic calibration, HAR volatility support, and optional Chronos/LightGBM boundaries.
- `app/strategy`: deterministic conviction/risk policy, absorption/confirmation gates, abstention, sizing, and decision reasons.
- `app/backtesting`: frozen fixture replay, deterministic strategy runs, research reports, immutable run artifacts, and verification.
- `app/execution`: disabled/replay/PAPER modes, Alpaca paper provider, kill switch, idempotency, reconciliation, and no LIVE execution.
- `app/observability`: structured logging, request/trace IDs, Prometheus-compatible metrics, pool/session metrics, and operational health.

## Persistence and integrity

PostgreSQL is the system of record for canonical events, market observations, world evidence, graph snapshots, cause investigations, forecast vintages/actuals/evaluations, simulations, execution intents/fills/transitions, and audits. Alembic is at head. Immutable ledger and snapshot protections are tested. The checked-in graph seed validates at 105 nodes, 52 companies, and 85 edges.

The local AURE CLI was inspected and its verified commands include `init`, `info`, `db check`, `query`, `serve`, and stdio `mcp`. ECHO currently keeps the deterministic graph path active and reports AURE as optional/unconfigured unless an operator supplies a verified binary and `.auredb` path.

## Providers and modes

- Replay: deterministic market/world fixtures with no external credentials.
- Massive: official Python/WebSocket adapter; API key required for hosted data.
- World Monitor: documented REST/MCP adapter; credentials/quota remain external.
- Alpaca: official SDK market fallback and paper execution; credentials and paper flag required.
- JEV: optional and not required for startup.
- Global `ECHO_MODE` and provider-specific settings are explicit; missing optional credentials degrade status instead of exposing secrets or blocking replay.

## Frontend

The frontend is Next.js 16 + React 19 + TypeScript. It has 82 TypeScript/TSX files and 20 test files covering shell/navigation, event cards/timeline/source evidence, market status/charts/shocks, graph/forecast/strategy workspaces, world mode, operational status, API clients, loading/error/empty states, and accessibility-oriented interactions. The typed API clients centralize request/error handling and use `NEXT_PUBLIC_API_URL` only; provider secrets never enter browser configuration.

## Artifacts and operational evidence

The repository contains replay data, forecast bundles, strategy cards, backtest CSV/JSON/Markdown outputs, Day 11 benchmarks, release manifests, audit reports, and model registries. This E2E run added the following evidence directory:

- `summary.json`: aggregate API/UI/deep-domain result.
- `api-responses.json`: 13 API endpoint responses.
- `frontend-pages.json`: 6 Next.js route probes.
- `deep-domain-responses.json`: initial intentionally invalid semantic probes retained for auditability.
- `corrected-domain-responses.json`: valid market-shock/cause/graph/forecast/backtest flow.
- `gate-results.json`: all validation gates and host blockers.
- `run-metadata.json`: replay providers, database mode, and Docker note.
- `browser-status.json`: Chromium dependency limitation.

The valid flow returned 13/13 API probes, 6/6 frontend route probes, and 8/9 corrected deep calls. The one expected 503 is the temporal graph-snapshot guard for a world event with no graph snapshot available at its event cutoff. The market-shock flow passed and returned a cause investigation with status `UNKNOWN` plus a forecast preview with `FORECAST_UNAVAILABLE`/OOD diagnostics, which is correct safe behavior for missing causal features rather than fabricated output.

## Verified quality gates

- Backend: 1,336 passed, 90 skipped.
- Frontend: 163 passed; typecheck, lint, and production build passed.
- Alembic drift: no new upgrade operations.
- Backtest verification: `verified: true`, no differences.
- Paper dry run: replay intent created, broker not called.
- Release manifest: verified with no differences.
- Docker compose start: host-blocked by cgroup configuration; no destructive reset was performed.
- Chromium automation: host-blocked by missing `libasound.so.2`; HTTP-rendered frontend evidence passed.

## Remaining boundaries

The product is replay/demo-complete and strongly tested. Live provider health is not proven without external credentials/quota. Neon is configuration-ready but the current run used local PostgreSQL. AURE is capability/status-ready with deterministic fallback, not yet the active graph persistence path. Chronos/LightGBM/ModernFinBERT remain optional/degraded where artifacts or packages are unavailable. Browser automation needs the missing host audio library or a compatible browser runtime.
