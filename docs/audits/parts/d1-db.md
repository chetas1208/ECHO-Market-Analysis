# D1 audit: DB migrations (fresh db `audit_migr`)
Scope: read-only on code. DB `audit_migr` created, used, dropped. Migrations 0001..0003 in backend/migrations/versions.
Cmd: `DATABASE_URL=postgresql+asyncpg://echo:echo_dev_password@localhost:5433/audit_migr uv run alembic upgrade head` (from backend/).

## 1. Upgrade head on empty db
- Check: `alembic upgrade head` succeeds from empty db.
- Result: PASS.
- Evidence: Running upgrade -> 0001 canonical_events; 0001 -> 0002 forecast ledger; 0002 -> 0003 market_observations. `alembic current` = `0003 (head)`; `alembic heads` = `0003 (head)` (single head, linear chain).
- Status: PASS

## 2. Required tables exist
- Check: canonical_events, forecast_runs, forecast_points, market_observations exist.
- Result: all 4 present (+ alembic_version).
- Evidence: `\dt` lists public.{alembic_version, canonical_events, forecast_points, forecast_runs, market_observations}, owner echo.
- Status: PASS

## 3. Indexes (`\di`)
- Check: expected lookup indexes + PK/unique present.
- Result: 13 indexes, all sane.
- Evidence:
  - canonical_events: canonical_events_pkey(id); ix_canonical_events_timestamp; ix_canonical_events_source_type; ix_canonical_events_event_type
  - forecast_runs: forecast_runs_pkey(id); ix_forecast_runs_event_id; ix_forecast_runs_symbol_prediction_timestamp(symbol, prediction_timestamp)
  - forecast_points: forecast_points_pkey(id); uq_forecast_points_forecast_run_id_horizon UNIQUE(forecast_run_id, horizon) (also serves FK-side lookup on forecast_run_id as leading column)
  - market_observations: market_observations_pkey(id); ix_market_observations_symbol_timestamp(symbol, timestamp); uq_market_observations_symbol_timestamp_source_timeframe UNIQUE(symbol, timestamp, source, timeframe)
  - alembic_version_pkc
- Note: no index on forecast_points.target_timestamp or canonical_events.ingested_at; no query need shown yet, informational only.
- Status: PASS

## 4. Timestamp column types
- Check: every timestamp column is timestamptz.
- Result: 10/10 timestamp-like columns are `timestamp with time zone`; zero `timestamp without time zone` columns in schema.
- Evidence: information_schema.columns: canonical_events(timestamp, created_at, ingested_at); forecast_runs(created_at, prediction_timestamp, data_cutoff_at); forecast_points(created_at, target_timestamp); market_observations(timestamp, created_at) all `timestamp with time zone`. Insert of '2026-01-02 09:30-05' reads back as 14:30 UTC (tz-correct).
- Status: PASS

## 5. Other column types / defaults
- Check: types, nullability, defaults sensible.
- Result: PASS. ids: canonical_events.id text (CHECK ^evt_[a-z0-9_]+$); forecast_*.id uuid DEFAULT gen_random_uuid(); market_observations.id bigserial. jsonb NOT NULL with '[]'/'{}' defaults; scores/quantiles/prices/volume `numeric` (unbounded); trade_count bigint; horizon_trading_days integer; timeframe default '1m'; is_mock default false.
- Status: PASS

## 6. CHECK constraints
- Check: CHECKs present and actually enforced.
- Result: 13 (canonical_events) + 3 (forecast_runs) + 4 (forecast_points) + 8 (market_observations) = 28, all present; 15 negative DML probes all rejected with the expected constraint.
- Evidence:
  - canonical_events: id_format, source_type IN (WORLD|MARKET|FINANCIAL), title_nonempty, entities/companies/locations/source_refs=array, economic_channels/metadata=object, severity/novelty/corroboration/confidence in [0,1]. Probes: 'BAD' id, 'world' lowercase, severity 1.5, economic_channels='[]' all rejected.
  - forecast_runs: symbol_nonempty, cutoff_not_after_prediction (data_cutoff_at <= prediction_timestamp), metadata_object. Probe: cutoff +1h rejected.
  - forecast_points: horizon IN (1D,2D,5D,10D,20D), horizon_days_match (pair check), quantile_order (q10<=q50<=q90), probability_positive [0,1]; UNIQUE(run, horizon). Probes: 2D/1 day, q10>q50, p=1.2, duplicate (run,horizon) rejected.
  - market_observations: symbol/source nonempty, timeframe ~ '^[0-9]+[mhd]$', prices_nonneg, high>=low, ohlc_within_range, volume_nonneg, trade_count_nonneg; UNIQUE(symbol,timestamp,source,timeframe). Probes: high<low, close>high, volume -1, timeframe '1x', duplicate bar rejected.
- Status: PASS

## 7. Foreign keys / ON DELETE RESTRICT
- Check: all FKs are ON DELETE RESTRICT.
- Result: PASS, 2 FKs, both confdeltype='r'.
- Evidence: forecast_runs_event_id_fkey (event_id -> canonical_events.id) ON DELETE RESTRICT (nullable column); forecast_points_forecast_run_id_fkey (forecast_run_id -> forecast_runs.id) ON DELETE RESTRICT (NOT NULL). ON UPDATE = NO ACTION (default). Probes: insert with unknown event_id rejected; DELETE canonical_events row referenced by a run rejected (FK violation); TRUNCATE canonical_events CASCADE rolled back because it reaches ledger tables and the truncate trigger fires.
- Status: PASS

## 8. Ledger immutability triggers (D-005)
- Check: forecast_runs / forecast_points append-only in DB.
- Result: PASS. 4 triggers enabled (`O`): trg_<t>_immutable_row (BEFORE UPDATE OR DELETE, FOR EACH ROW) and trg_<t>_immutable_truncate (BEFORE TRUNCATE) on both tables, function echo_forbid_ledger_mutation().
- Evidence: UPDATE/DELETE on both tables and TRUNCATE forecast_points all raise "is an immutable, append-only ledger" (ERRCODE restrict_violation). Plain TRUNCATE forecast_runs blocked by FK first.
- Status: PASS
- Residual (Low, informational): the app role `echo` owns the tables, so it can DROP TRIGGER / ALTER TABLE DISABLE TRIGGER / set session_replication_role. `alembic downgrade` also drops ledger data (see 10). Hardening option: separate migration-owner role vs app role with INSERT/SELECT only on ledger tables.

## 9. Drift vs SQLAlchemy models (backend/app/models)
- Check: models vs live schema, and `alembic check`.
- Result: columns/types/nullability/server defaults/FK targets+ondelete = NO DRIFT (all DateTime(timezone=True), Numeric(asdecimal=False), JSONB, UUID(as_uuid), BigInteger match; alembic compares types/defaults and emitted no alter_column). STRUCTURAL DRIFT exists: models declare none of the indexes, unique constraints, CHECKs or triggers that migrations create.
- Evidence: `uv run alembic check` exits FAILED "New upgrade operations detected": 8 x remove (ix_canonical_events_{timestamp,source_type,event_type}; ix_forecast_runs_event_id; ix_forecast_runs_symbol_prediction_timestamp; ix_market_observations_symbol_timestamp; uq_forecast_points_forecast_run_id_horizon; uq_market_observations_symbol_timestamp_source_timeframe). CHECKs (28) and triggers (4) are invisible to autogenerate so they would not be flagged, but are also absent from models (create_all() on models would yield a schema without them).
  - Naming: Base.metadata naming_convention gives pk_%(table)s and fk_%(col)s_%(ref)s but migrations use raw SQL so live names are PG defaults (canonical_events_pkey, forecast_runs_event_id_fkey, forecast_points_forecast_run_id_fkey). ix_/uq_/ck_ names match the convention. Cosmetic; matters only if a future migration drops/renames PK/FK by convention name.
- Repair (not applied, read-only task): add `__table_args__` (Index, UniqueConstraint, CheckConstraint) to the 4 models, or add `include_object` in migrations/env.py to ignore them; align PK/FK names in a migration or drop the pk/fk convention keys. Risk if unfixed: a developer running `alembic revision --autogenerate` gets a migration that DROPS 8 indexes/uniques; backend/tests/conftest.py builds the test DB via `command.upgrade(..., 'head')` (no create_all), so tests exercise the real CHECKs/triggers. Only ad-hoc create_all use would lose them.
- Status: WARN (Medium/Low, no runtime impact today)

## 10. Round trip downgrade base -> upgrade head
- Check: downgrade base then upgrade head, with rows present; schema identical after.
- Result: PASS.
- Evidence: downgrade 0003->0002->0001->base ran clean with 1 event, 1 run, 1 point, 2 bars loaded (DROP TABLE not blocked by immutability triggers); afterwards only alembic_version (+pkey) remained, function echo_forbid_ledger_mutation() gone (pg_proc empty), no orphan objects. Re-upgrade ran 0001..0003; `pg_dump --schema-only` before vs after diff is EMPTY (SCHEMA_IDENTICAL). A second full down/up cycle on empty data also ran 3+3 steps; re-running `upgrade head` at head is a no-op (0 steps).
- Note (Low): downgrade destroys ledger rows by design; acceptable for dev, should never be run against prod.
- Status: PASS

## Cleanup
- `DROP DATABASE audit_migr` executed at end (confirmed absent from pg_database). DBs `echo`, `echo_test` untouched. No code changed.
