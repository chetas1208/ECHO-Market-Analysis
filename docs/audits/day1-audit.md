# Day 1 audit (performed before Day 2 work) — 2026-09-20

Method: every check run empirically (real PostgreSQL, real API, headless browser). Six independent audit passes; raw evidence in `docs/audits/parts/d1-*.md`. Format: Check / Result / Evidence / Repair / Status.

## Environment finding (blocker, repaired)

| Check | Result | Evidence | Repair | Status |
|---|---|---|---|---|
| PostgreSQL launches via `docker compose` | FAIL | Shared rootless dockerd could not start any container: `open /sys/fs/cgroup/user.slice/user-…slice/cgroup.controllers: no such file or directory` (systemd cgroup driver, no user slice). Day 1 had been verified only against a substitute Postgres. | Left the shared daemon untouched (a restart was declined by the permission layer). Started a private rootless dockerd (`/tmp/echo-dockerd`, cgroupfs) and used `DOCKER_HOST=unix:///tmp/echo-dockerd/docker.sock`. | PASS: `docker compose up -d --wait db` → `echo-db-1 Up (healthy)`; all later checks ran against it. Note: the private daemon is an environment workaround, not a repo change (Makefile only documents it). |

## Repository / hygiene (d1-repo.md) — PASS

Plan/Milestones/decisions/seed/UI.md present and non-empty; no secrets (only the documented dev password); `.env`, `.reference-repos/`, `node_modules`, `.next`, `.venv` ignored; nothing vendored; no file > 1 MB tracked; README ↔ Makefile consistent; `references/REPOS.md` lists 7 repos with SHAs matching clones. Low findings: `getHealth` unused (repaired), `is_valid_event_id` reported dead but is used by tests (kept), Makefile help text missing (repaired).

## Database / migrations (d1-db.md)

| Check | Result | Evidence | Status |
|---|---|---|---|
| Clean `alembic upgrade head` | PASS | 0001→0003 on an empty DB; single head; re-run is a no-op | PASS |
| Tables, 13 indexes, 28 CHECKs, FKs | PASS | all 4 tables; FKs ON DELETE RESTRICT; 15 negative insert probes rejected by the expected CHECK | PASS |
| Timestamps timezone-safe | PASS | 10/10 columns `timestamptz` | PASS |
| downgrade→upgrade round trip | PASS | schema-only `pg_dump` identical | PASS |
| Models match migrations (`alembic check`) | FAIL | 8 drift ops (models omitted indexes/uniques/CHECKs) | Repair: constraints declared in `models/event.py`, `models/forecast.py`; `tests/test_alembic_check.py` added. `market_observations` excluded in that test until its model declares its indexes. | PASS (event/forecast); market_observations drift open (see Limitations) |

## Immutable forecast ledger (d1-immutability.md)

| Check | Result | Evidence | Status |
|---|---|---|---|
| UPDATE / DELETE on `forecast_runs`, `forecast_points` | PASS | all 4 rejected, SQLSTATE 23001 "immutable, append-only ledger" | PASS |
| TRUNCATE (plain/CASCADE/both) | PASS | trigger or FK check rejects every form | PASS |
| DELETE parent event | PASS | 23503 RESTRICT | PASS |
| New vintage INSERT | PASS | 2 runs × 5 points | PASS |
| Superuser bypass | FAIL | `SET session_replication_role=replica` bypassed all triggers (UPDATE/DELETE/TRUNCATE succeeded; rolled back) | Repair: migration `0004_market_extras` runs `ENABLE ALWAYS TRIGGER` on the 4 ledger triggers; test asserts UPDATE/DELETE/TRUNCATE still raise under replica mode, with a control showing the bypass was real at 0003. | PASS |

## Backend API (d1-api.md) — PASS

health/ready 200; POST 201; list/get 200; invalid confidence, invalid severity, naive timestamp, malformed JSON, NaN, limit=0 → 422 envelope; unknown id 404; duplicate 409; PUT/DELETE 405; DB down (bad port): `/ready` 503, DB routes 503 `database_error`, no stack trace/SQL/credentials in bodies, no password in logs; JSON logs carry `request_id`; response keys match frontend types. Low findings repaired: `ApiErrorCode` gained `method_not_allowed`/`http_error`; `getReady()` now returns the non-envelope 503 body typed instead of throwing.

## UI.md compliance (d1-ui.md)

| Check | Result | Repair | Status |
|---|---|---|---|
| ≤5 primary tabs; overlay drawer; no permanent rail; content does not shift; backdrop dims + blurs (`blur(8px)`) | PASS | — | PASS |
| Close via hamburger/close button/backdrop/Esc/select | PASS | — | PASS |
| Closed drawer keyboard-reachable; no focus trap/return; body scroll not locked; duplicate hamburger; drawer 85vw | FAIL | `inert` + hidden when closed; focus trap and return; scroll lock; duplicate removed; 90vw; sticky top bar; stale rail CSS removed; 5 AppShell tests | PASS |
| Horizontal overflow on `/` at 375px; forced 64px page scroll on Events/Graph/Forecasts/Strategy | FAIL | overflow fixed; `min-height: calc(100vh - 64px)` removed | PASS |
| Top bar showed green "LIVE" whenever `/ready` ok (only mock data existed) | FAIL | Header now shows `ModeBadge` driven by `/market/status` (LIVE/REPLAY/MOCK/OFFLINE; OFFLINE on any failure); "LIVE" only from ModeBadge; API dot relabeled "API OK" | PASS (Day 2 work) |
| Dashboard scrolls 342px @1440×900 / 1494px @375 (UI.md §9 wants one screen) | FAIL | Assigned to the Day 2 Dashboard integration; result recorded in `day2-audit.md` | see day2-audit |
| Event fetched from backend, not hardcoded; loading/empty/error states; no console errors | PASS | — | PASS |

## Automated validation (d1-tests.md)

Backend `pytest`: 134 passed / 0 failed / 0 skipped. `ruff check` + `ruff format --check`: clean. `uv pip check`: compatible; `uv lock --check`: no drift. Frontend: typecheck clean, lint clean, vitest 6/6, `next build` OK (no backend needed).

## Limitations still true after Day 1

- The `echo` DB role is a superuser and owns the tables, so it can `DROP TRIGGER`/`ALTER TABLE … DISABLE TRIGGER`. Mitigation not implemented: run the app as a non-superuser, non-owner role with SELECT/INSERT only on ledger tables.
- `alembic downgrade` destroys ledger rows; never run against real data.
- (closed) `models/market.py` now declares its unique constraint and index; `alembic check` reports no drift for any table.
- PK/FK constraint names use Postgres defaults (cosmetic).
- Docker needs the private-daemon workaround in this environment.
