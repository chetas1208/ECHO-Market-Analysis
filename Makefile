# ECHO — local dev commands. Run from repo root.
#
# Docker note: in the sandboxed dev environment Docker may need a private rootless
# daemon. If `docker compose` cannot reach the default daemon, export before make:
#   DOCKER_HOST=unix:///tmp/echo-dockerd/docker.sock
# (deliberately not hardcoded here; on a normal machine leave DOCKER_HOST unset.)
SHELL := /bin/bash
UV ?= $(shell command -v uv 2>/dev/null || echo $$HOME/.local/bin/uv)
ENV_FILE := .env
API_HOST ?= 127.0.0.1
API_PORT ?= 8100

.PHONY: help setup env db-up db-down db-reset migrate seed graph-validate graph-snapshot api web dev dev-replay demo-reset demo test test-backend test-frontend lint typecheck build check refs backfill-actuals backtest-final backtest-verify strategy-research paper-trade paper-dry-run bench-day11 verify-release check-env bootstrap check-live check-paper

help:
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | sed 's/:.*##/\t/' | column -t -s $$'\t'

env: ## create .env from .env.example if missing
	@test -f $(ENV_FILE) || cp .env.example $(ENV_FILE)

setup: env ## install backend + frontend dependencies
	cd backend && $(UV) sync
	cd frontend && pnpm install

db-up: env ## start PostgreSQL (docker compose) and wait until healthy
	docker compose up -d --wait db

db-down: ## stop PostgreSQL (keeps data)
	docker compose down

db-reset: ## DESTROY local DB volume, restart, migrate
	docker compose down -v
	$(MAKE) db-up migrate

migrate: ## apply Alembic migrations
	cd backend && $(UV) run alembic upgrade head

seed: ## insert the mock World Monitor-style event (idempotent)
	cd backend && $(UV) run python -m app.scripts.seed

graph-validate: ## validate the checked-in ShockGraph seed artifact
	python scripts/validate_graph.py

graph-snapshot: graph-validate migrate ## validate and create an immutable ShockGraph snapshot
	cd backend && $(UV) run python -m app.scripts.graph_snapshot

api: ## run FastAPI with reload on API_HOST:API_PORT
	cd backend && $(UV) run uvicorn app.main:app --reload --host $(API_HOST) --port $(API_PORT)

web: ## run Next.js dev server on :3000
	cd frontend && pnpm dev

dev: db-up migrate seed ## db + migrate + seed, then API and web together (Ctrl-C stops both)
	@trap 'kill 0' INT TERM; $(MAKE) api & $(MAKE) web & wait

dev-replay: ## like dev, but API runs the offline replay market feed (no keys)
	@$(MAKE) db-up migrate seed
	@trap 'kill 0' INT TERM; ECHO_MARKET_PROVIDER=replay $(MAKE) api & $(MAKE) web & wait

demo-reset: db-reset seed graph-snapshot ## reset local demo state, seed graph, and disable execution
	@echo "Demo state reset: replay data is deterministic and paper execution remains DISABLED."

demo: migrate seed graph-snapshot ## launch the offline-safe replay demo (no broker or live-feed calls)
	@trap 'kill 0' INT TERM; ECHO_MARKET_PROVIDER=replay ECHO_WORLD_PROVIDER=replay ECHO_EXECUTION_MODE=DISABLED $(MAKE) api & $(MAKE) web & wait

test: test-backend test-frontend ## all automated tests

test-backend: ## backend pytest (needs `make db-up`)
	cd backend && $(UV) run pytest

test-frontend: ## frontend vitest
	cd frontend && pnpm test

lint: ## ruff + eslint
	cd backend && $(UV) run ruff check .
	cd frontend && pnpm lint

typecheck: ## frontend tsc --noEmit
	cd frontend && pnpm typecheck

build: ## production frontend build
	cd frontend && pnpm build

check: lint typecheck test build ## everything Day 1 requires

refs: ## shallow-clone reference repos into .reference-repos/ (optional)
	./scripts/fetch_reference_repos.sh

backfill-actuals: ## append due CAR observations; requires FORECAST_ID and AS_OF
	@test -n "$(FORECAST_ID)" && test -n "$(AS_OF)" || (echo 'usage: make backfill-actuals FORECAST_ID=... AS_OF=...'; exit 2)
	cd backend && $(UV) run python -m app.forecasting.backfill_actuals --forecast-id "$(FORECAST_ID)" --as-of "$(AS_OF)"

backtest-final: ## run the frozen registered strategy against the configured replay dataset
	cd backend && $(UV) run python -m app.backtesting.cli final

backtest-verify: ## verify the frozen replay reproduces the existing immutable artifact
	cd backend && $(UV) run python -m app.backtesting.cli verify

strategy-research: ## run the bounded strategy-family and robustness smoke research
	cd backend && $(UV) run python -m app.backtesting.cli research

paper-trade: ## verify the explicitly enabled Alpaca PAPER execution profile; never starts LIVE trading
	@cd backend && ECHO_EXECUTION_MODE=PAPER $(UV) run python -m app.execution.cli status

paper-dry-run: ## validate a registered paper decision without submitting an order
	@cd backend && ECHO_EXECUTION_MODE=REPLAY $(UV) run python -m app.execution.cli dry-run

bench-day11: ## run deterministic Day 11 benchmark suite and write artifacts/benchmarks/day11
	cd backend && $(UV) run python ../benchmarks/day11.py

verify-release: ## verify the immutable hackathon release hashes
	python scripts/verify_hackathon_release.py

check-env: ## print secret-free provider and database configuration status
	cd backend && $(UV) run python ../scripts/check_env.py
	cd backend && $(UV) run python ../scripts/check_aure.py
	cd backend && $(UV) run python ../scripts/check_mcp.py

bootstrap: check-env ## validate configuration, database, migrations, and graph artifacts
	cd backend && $(UV) run python ../scripts/check_neon.py --strict
	cd backend && $(UV) run python ../scripts/check_aure.py
	$(MAKE) migrate
	$(MAKE) graph-validate
	@echo "Bootstrap checks complete; no provider credentials or graph database are created."

check-live: ## strict read-only checks for configured live dependencies
	cd backend && $(UV) run python ../scripts/check_env.py --strict
	cd backend && $(UV) run python ../scripts/check_neon.py --strict
	cd backend && $(UV) run python ../scripts/check_aure.py --strict
	cd backend && $(UV) run python ../scripts/check_mcp.py --live --strict

check-paper: ## validate Alpaca PAPER settings without submitting an order
	cd backend && $(UV) run python ../scripts/check_paper.py --strict

docker-check: ## validate docker-compose.yml (docker compose config -q)
	docker compose config -q
