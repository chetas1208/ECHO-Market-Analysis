# ECHO production deployment (Day 11 foundation)

## Current deployment shape

The supported deployment is one FastAPI backend, one Next.js frontend, and PostgreSQL. Market and
world providers are optional and may run in `REPLAY`, `LIVE`, or `OFFLINE`/unconfigured states.
Execution defaults to `DISABLED`; only an explicitly configured Alpaca PAPER adapter is allowed.
There is no live-money path.

Start in a clean environment:

```bash
make env
make db-up
make migrate
make seed
make graph-snapshot
ECHO_MARKET_PROVIDER=replay ECHO_WORLD_PROVIDER=replay ECHO_EXECUTION_MODE=DISABLED make api
```

The frontend uses `NEXT_PUBLIC_API_URL` and should be served separately. Liveness is
`GET /api/v1/health`; dependency readiness is `GET /api/v1/ready`; the richer operational view is
`GET /api/v1/ops/status`; Prometheus scrapes `GET /metrics`.

## Configuration and secrets

Keep code defaults, provider settings, strategy/model versioned configs, and secrets separate.
Local development uses `.env`; production should inject a secret-manager reference (Vault, AWS
Secrets Manager, or GCP Secret Manager) into the process environment. Never put provider keys in
frontend variables, logs, benchmark output, or event payloads.

## Storage and backups

PostgreSQL is the source of truth for canonical events, graph snapshots, forecast ledger rows,
execution intents/fills, and reconciliation records. Take a custom-format `pg_dump` before schema
migrations and retain immutable records longer than raw packets. A restore must run migrations,
validate the Alembic head, verify immutable-table hashes, and replay only derived data.

Example operator procedure:

```bash
pg_dump --format=custom --file=echo-$(date -u +%Y%m%dT%H%M%SZ).dump "$DATABASE_URL"
createdb echo_restore
pg_restore --exit-on-error --dbname="$RESTORE_DATABASE_URL" echo-*.dump
DATABASE_URL="$RESTORE_DATABASE_URL" make migrate
```

Run these commands from a controlled backup directory; do not overwrite the production database.

## Scaling boundary

Scale the API horizontally only after DB pool capacity and benchmark baselines are reviewed. Keep
ingestion, graph, forecast, and execution process boundaries explicit. Redpanda, Kubernetes, Rust,
and larger universes are future decisions, not current deployment claims.
