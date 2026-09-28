# ECHO

ECHO is an event-conditioned market intelligence terminal. It maps real-world
events through explicit economic relationships, estimates abnormal-return
distributions, preserves every forecast vintage, and acts only through a
deterministic risk gate.

> ECHO does not predict whether news is bullish or bearish. It estimates how
> economically meaningful information should propagate through connected
> companies, measures how much of that impact the market has already absorbed,
> and acts only on the remaining propagation gap.

## Product surface

The UI has five primary destinations: Dashboard, Events, Graph, Forecasts, and
Strategy. Backtesting, simulation, ledger inspection, risk, and paper status are
subviews rather than additional navigation tabs.

Architecture:

```text
World Monitor ──┐
                ├──> Canonical events ──> ShockGraph ──> Forecast
Market data ────┘                                      │
                                                       ▼
                                                  Risk gate
                                                ┌──────┴──────┐
                                                ▼             ▼
                                             Abstain      Paper trade
                                                              │
                                                              ▼
                                                        Alpaca PAPER
```

## Quick start

Requirements: Docker Compose, Python 3.12+, `uv`, Node 22+, and `pnpm`.

```bash
make setup
make demo-reset   # clean local PostgreSQL, migrations, seed, graph snapshot
make demo         # deterministic replay UI/API; no live feed or broker calls
```

Open <http://localhost:3000>. The global header always exposes data mode
(`LIVE`, `REPLAY`, `MOCK`, or `OFFLINE`) and execution mode (`SIMULATION` or
`PAPER`). Replay is never labelled live.

For normal development:

```bash
make dev          # database, migrations, mock event, API, web
make dev-replay   # same stack with deterministic market replay
```

## Research and safety

The locked resource and technology boundary is documented in
[`docs/resource-plan.md`](docs/resource-plan.md). Optional models and future infrastructure are
explicitly separated from the replay-safe core.

- `echo-rp-v1` is the frozen strategy artifact; its config hash is recorded in
  `artifacts/release/manifest.json`.
- Forecasts are abnormal returns with q10/q50/q90, horizons, cutoffs, graph
  snapshot identity, feature hashes, and content hashes.
- Ledger and graph snapshot records are append-only and protected by database
  constraints/triggers.
- Execution defaults to `DISABLED`; `LIVE` is rejected. Only validated
  `PAPER_TRADE` decisions can reach the Alpaca paper adapter.
- Alpaca paper trading is simulated broker execution. It is not proof of live
  profitability and does not model all impact, latency, queue, or slippage
  effects.

## Data modes

Set `ECHO_MODE` explicitly to `offline`, `replay`, or `live`. Market providers
use `ECHO_MARKET_PROVIDER` (`off`, `replay`, `massive`, or `alpaca`) and world
feeds use `ECHO_WORLD_PROVIDER`. Missing credentials degrade cleanly instead of
blocking API startup. Use `make check-env` for a secret-free summary and
`GET /api/v1/system/config-status` for the same state from the API.

Replay setup requires only the checked-in fixtures and local PostgreSQL. Hosted
Neon, Massive, World Monitor, and Alpaca credentials are not supplied by their
source repositories. `make check-live` performs strict read-only checks; it
does not create accounts, fetch repositories, or place orders. Alpaca paper
execution requires `ALPACA_PAPER=true` (the MCP-compatible
`ALPACA_PAPER_TRADE=true` alias is also accepted); LIVE execution is rejected.

The local graph integration is explicit: `GRAPH_BACKEND=networkx` is the safe
default and `GRAPH_FALLBACK_BACKEND=networkx` is used if configured AURE paths
are unavailable. AURE validation uses only the verified read-only command
`aure db check <path> --output json`; it never initializes or mutates a graph
database during `make bootstrap`.

## Verification

```bash
make test
make lint
make typecheck
make build
make backtest-final
make paper-dry-run
make check-env
make bootstrap
```

The checked-in replay run is synthetic contract evidence: 18 trades, 1.2903%
total return, 0.2182% max drawdown, 83.33% hit rate, and status
`INSUFFICIENT_DATA`. It does not support a live-performance or final-holdout
claim.

## Demo and judge material

- [Three-to-five-minute demo script](docs/demo-script.md)
- [Technical judge brief](docs/judges.md)
- [Judge Q&A](docs/judge-qa.md)
- [Pitch outline](docs/pitch-outline.md)
- [Final test matrix](docs/final-test-matrix.md)
- [Final audit](docs/audits/final-audit.md)
- [Release manifest](artifacts/release/manifest.json)

## Project structure

```text
backend/       FastAPI, domain services, migrations, replay providers, tests
frontend/      Next.js UI, typed API client, accessible five-tab shell
configs/       Frozen strategy configuration
artifacts/     Replay, strategy, demo, audit, and release evidence
docs/          Contracts, architecture, runbooks, and audit records
scripts/       Safe validation and demo utilities
```
