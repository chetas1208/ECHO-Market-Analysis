# D1 Audit: ledger immutability at real PostgreSQL level

- Date: 2026-09-20. PostgreSQL 16.15 (container `echo-db-1`, port 5433). Role `echo` is SUPERUSER (rolsuper=t).
- DB `audit_immut` created, `alembic upgrade head` ran 0001 -> 0002 -> 0003 clean. DB dropped at end (plus temp role `audit_app`).
- Mechanism found (migration 0002): function `echo_forbid_ledger_mutation()` raises SQLSTATE 23001 (restrict_violation): `table "%" is an immutable, append-only ledger: % is not allowed`. Triggers (all enabled, tgenabled=O):
  - `trg_forecast_runs_immutable_row`, `trg_forecast_points_immutable_row`: BEFORE DELETE OR UPDATE, FOR EACH ROW
  - `trg_forecast_runs_immutable_truncate`, `trg_forecast_points_immutable_truncate`: BEFORE TRUNCATE, FOR EACH STATEMENT
  - FKs: `forecast_runs.event_id -> canonical_events(id) ON DELETE RESTRICT`; `forecast_points.forecast_run_id -> forecast_runs(id) ON DELETE RESTRICT`.

## Seed
- 1 canonical event `evt_audit_1` (WORLD), 1 run `1111...`, 5 points (1D,2D,5D,10D,20D; q10<=q50<=q90, horizon_trading_days match). All accepted by CHECKs.

## Check 1: UPDATE/DELETE on ledger tables (superuser `echo`, default replication role)
| Statement | Result | Exact error |
|---|---|---|
| `UPDATE forecast_runs SET symbol='MSFT'` | REJECTED | `ERROR: 23001: table "forecast_runs" is an immutable, append-only ledger: UPDATE is not allowed` |
| `DELETE FROM forecast_runs` | REJECTED | `... table "forecast_runs" is an immutable, append-only ledger: DELETE is not allowed` |
| `UPDATE forecast_points SET q50=0.5` | REJECTED | `... table "forecast_points" is an immutable, append-only ledger: UPDATE is not allowed` |
| `DELETE FROM forecast_points` | REJECTED | `... table "forecast_points" is an immutable, append-only ledger: DELETE is not allowed` |

## Check 2: TRUNCATE
| Statement | Result | Exact error |
|---|---|---|
| `TRUNCATE forecast_points` | REJECTED (trigger) | `ERROR: 23001: table "forecast_points" is an immutable, append-only ledger: TRUNCATE is not allowed` |
| `TRUNCATE forecast_runs` (plain) | REJECTED (FK, before trigger) | `ERROR: 0A000: cannot truncate a table referenced in a foreign key constraint` / `DETAIL: Table "forecast_points" references "forecast_runs".` |
| `TRUNCATE forecast_runs CASCADE` | REJECTED (trigger) | `NOTICE: truncate cascades to table "forecast_points"` then `ERROR: 23001: table "forecast_runs" is an immutable, append-only ledger: TRUNCATE is not allowed` |
| `TRUNCATE forecast_points CASCADE` | REJECTED (trigger) | `ERROR: 23001: table "forecast_points" ... TRUNCATE is not allowed` |
| `TRUNCATE forecast_runs, forecast_points` | REJECTED (trigger) | `ERROR: 23001: table "forecast_runs" ... TRUNCATE is not allowed` |
| `TRUNCATE forecast_runs, forecast_points CASCADE` | REJECTED (trigger) | `ERROR: 23001: table "forecast_runs" ... TRUNCATE is not allowed` |
| `TRUNCATE canonical_events` (extra) | REJECTED (FK) | `ERROR: 0A000: cannot truncate a table referenced in a foreign key constraint` / `DETAIL: Table "forecast_runs" references "canonical_events".` |
| `TRUNCATE canonical_events CASCADE` (extra) | REJECTED (trigger) | NOTICE cascades to `forecast_runs`, `forecast_points`, then `ERROR: 23001: table "forecast_runs" ... TRUNCATE is not allowed` |

Note: canonical_events itself has no immutability trigger (only FK protection), so cascade truncate of it is stopped only because the cascade reaches the trigger-protected ledger tables.

## Check 3: DELETE parent event (RESTRICT)
`DELETE FROM canonical_events WHERE id='evt_audit_1'` -> REJECTED:
`ERROR: 23503: update or delete on table "canonical_events" violates foreign key constraint "forecast_runs_event_id_fkey" on table "forecast_runs"` / `DETAIL: Key (id)=(evt_audit_1) is still referenced from table "forecast_runs".`

Row counts after all attempts: runs=1, points=5, events=1 (nothing changed).

## Check 4: superuser bypass (KNOWN LIMITATION)
Run inside `BEGIN ... ROLLBACK` so ledger stayed intact, as superuser `echo`:
- `SET session_replication_role=replica;` -> accepted (`SHOW` = replica).
- `UPDATE forecast_runs SET symbol='TAMPERED'` -> **`UPDATE 1` (BYPASSED)**.
- `UPDATE forecast_points SET q50=0.0 WHERE horizon='1D'` -> `UPDATE 1`, row read back q50=0.0 (**BYPASSED**; an earlier attempt with q50=0.5 failed only on CHECK `ck_forecast_points_quantile_order`, which still applies under replica).
- `DELETE FROM forecast_points WHERE horizon='20D'` -> `DELETE 1` (BYPASSED; 4 rows).
- `TRUNCATE forecast_points` -> `TRUNCATE TABLE` (BYPASSED; 0 rows).
- After ROLLBACK: symbol=AAPL, points=5 (intact).
- Also bypassable by table owner/superuser: `ALTER TABLE forecast_runs DISABLE TRIGGER trg_forecast_runs_immutable_row; UPDATE ...` -> `UPDATE 1` (rolled back). `DROP TRIGGER` equally possible.
- Non-superuser role `audit_app` (granted SELECT/INSERT/UPDATE/DELETE): `SET session_replication_role=replica` -> `ERROR: permission denied to set parameter "session_replication_role"`; UPDATE/DELETE rejected by trigger (23001); TRUNCATE -> `permission denied for table forecast_points` (no TRUNCATE grant).

Conclusion: immutability is trigger-based, so it holds for all ordinary/non-superuser roles but NOT against a superuser or table owner (session_replication_role=replica, DISABLE TRIGGER, DROP TRIGGER). Documented limitation. Mitigation (not implemented): run the application as a non-superuser, non-owner role with only SELECT/INSERT on the ledger tables; optionally `ALTER TABLE ... ENABLE ALWAYS TRIGGER` on the four triggers, which makes them fire even under `replica` mode (DISABLE TRIGGER/DROP TRIGGER by owner still possible). Dev `echo` role is a superuser, so the running dev app has no protection from a compromised superuser connection.

## Check 5: new vintage INSERT still works
Inserted run `2222...` (model_version `m2`, same event/symbol, later prediction_timestamp) + 5 points -> `INSERT 0 1`, `INSERT 0 5`. Join shows m1: 5 pts, m2: 5 pts. Append-only path is unobstructed.

## Status
PASS with documented limitation (superuser/owner bypass). No code repairs made.
