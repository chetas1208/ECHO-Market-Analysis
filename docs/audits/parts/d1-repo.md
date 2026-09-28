# D1 Repo Hygiene Audit
Date 2026-09-20. Read-only (only this file written). Repo has 0 commits (`git log` -> "no commits yet"); every file is untracked-non-ignored, so "tracked" checks were done on `git ls-files -o --exclude-standard` (would-be-committed set).

## 1. Authoritative docs exist, non-empty
Check: Plan.md, Milestones.md, decisions.md, seed.md, UI.md at repo root.
Evidence (bytes): Plan.md 14438, Milestones.md 6807, decisions.md 8264, seed.md 9307, UI.md 47432.
Status: PASS.

## 2. Secrets
Check: grep -riE (api_key|secret|passw|token|bearer|PEM headers|sk-|AKIA|ghp_|wm_|xox) over all non-ignored files (excl node_modules/.venv/.next/.reference-repos/.git).
Result: only hits are
- `echo_dev_password` in `.env.example:7,9`, `docker-compose.yml:11` (`${POSTGRES_PASSWORD:-echo_dev_password}`), `backend/app/core/config.py:18` (DEFAULT_DATABASE_URL). All documented local dev default.
- Commented, empty future keys in `.env.example:20-26` (MASSIVE/ALPACA/WORLD_MONITOR/CONVICTION/JEV) - no values.
- Test fixtures: `"ignored-future-setting"`, `SECRET-PAYLOAD-TEXT`, `secret internal detail` (leak-guard assertions, not secrets). Rest are CSS/lockfile "tokens".
- `.env` (716 B) is byte-identical to `.env.example` (`diff` clean), so contains no extra secrets.
`.env` git-ignored: `git check-ignore -v .env` -> `.gitignore:1:.env`. `.gitignore` also has `.env.*` + `!.env.example`.
Status: PASS.

## 3. `git status --short --ignored`
Ignored (`!!`): `.env`, `.reference-repos/`, `backend/.venv/`, `backend/.pytest_cache/`, `backend/.ruff_cache/`, all `__pycache__/`, `frontend/.next/`, `frontend/node_modules/`, `frontend/next-env.d.ts`, `frontend/tsconfig.tsbuildinfo`. All four required (.reference-repos, node_modules, .next, .venv) ignored.
Untracked-to-be-added: `.env.example .gitignore Makefile Milestones.md Plan.md README.md UI.md YetToGo.md backend/ decisions.md docker-compose.yml docs/ frontend/ references/ scripts/ seed.md`.
Vendored repos: `find` for `.git`/`.gitmodules` outside .reference-repos/node_modules/.venv -> only root `./.git`. None vendored. 7 clone dirs live only in `.reference-repos/` (889M, ignored).
Big files: `find` excluding ignored dirs for files >1M -> none (so none >5M). Largest tracked-candidate is UI.md 47 KB / pnpm-lock.
Status: PASS.
Note (LOW): `docs/audits/parts/*.md` are not ignored; decide whether audit notes are meant to be committed. `YetToGo.md` (2.2 KB) is a scratch note not linked from README or any doc (grep: zero references); it is untracked-non-ignored so it would be committed. Either link it or move/ignore it.

## 4. README vs Makefile
Makefile targets: api build check db-down db-reset db-up dev env help lint migrate refs seed setup test test-backend test-frontend typecheck web.
README `make X` refs: api build check db-reset db-up dev env lint migrate refs seed setup test typecheck web. All exist in Makefile; port claims match (API 8100, web 3000, PG 5433 = .env.example/compose). README "make check = all of the above" matches `check: lint typecheck test build`.
Gap (LOW): `test-frontend`, `typecheck`, `db-down` styling: `test-frontend` and `typecheck` have no `## ` doc comment so they are absent from `make help` output (verified: help lists 16 targets, omits those two). README does not mention `test-backend`/`test-frontend`/`db-down` (harmless).
Repair not applied (read-only). Suggest adding `## ...` to both targets.
Status: PASS (1 LOW).

## 5. references/REPOS.md
Check: all 7 repos + "Last inspected" SHAs vs actual clone HEADs (`git -C .reference-repos/X rev-parse HEAD`).
| repo | REPOS.md | clone HEAD |
| worldmonitor | 4cb7fc1 | 4cb7fc1974de... OK |
| massive-client-python | 481e5c2 | 481e5c270ea8... OK |
| alpaca-py | 232179c | 232179c19091... OK |
| nautilus-trader | 9006e1e | 9006e1ea769c... OK |
| lean | 985ef30 | 985ef30ad3ac... OK |
| ib-async | ab629f3 | ab629f34c182... OK |
| ibind | 99b459b | 99b459bf240e... OK |
Summary table lists all 7 with tier/role/license/milestone. Short (7-char) SHAs, not full; acceptable.
Status: PASS.

## 6. scripts/fetch_reference_repos.sh
`ls -l`: `-rwxr-xr-x` (executable). Line 13 `set -euo pipefail`. `bash -n` OK. Same 7 repos as REPOS.md; `--depth 1 --single-branch`, `--filter=blob:none` for nautilus/lean; `--list`, `--update`, name validation, unknown-option exit 2. Only `rm -rf "${dest}"` (line 86) is on a failed partial clone of `${DEST_ROOT}/${name}`, always non-empty. No sudo. Not called by app/make except `make refs`.
Status: PASS.

## 7. docker-compose.yml
`docker compose config -q` -> valid (private daemon). Single `db` service postgres:16-alpine, port bound `127.0.0.1:5433:5432` (loopback only), named volume `echo_pgdata`, healthcheck via pg_isready with `$${VAR}` escaping, env defaults match .env.example, project `name: echo`. Container `echo-db-1` Up (healthy).
Status: PASS. (INFO: `restart: unless-stopped` fine for dev; no pinned patch tag - acceptable.)

## 8. Dead / duplicate code scan
Backend (`backend/app`): every non-`__init__` module is imported by at least one other module/test (min count 1: router.py, models/forecast.py, models/market.py, scripts/seed.py - all wired via router/alembic/Makefile). Top-level defs with a single occurrence: `create_event`, `get_event`, `list_events` are FastAPI route handlers (decorator-registered, not dead). `is_valid_event_id` at `backend/app/schemas/event.py:107` is defined and referenced nowhere (grep app/tests: 1 hit = definition) -> DEAD (LOW). Empty `__init__.py` x10 are normal packages.
Frontend: every component in `frontend/components`, `lib`, `types` is imported by at least one other file; all 4 `.module.css` are referenced by exactly one tsx. No duplicate-content files (md5 uniq -d empty). No TODO/FIXME/HACK in app code. No empty non-`__init__` files.
Unused: `getHealth` at `frontend/lib/api.ts:131` is exported but never imported anywhere (only definition). LOW; either use it (e.g., status indicator/AppShell) or delete.
Status: PASS with 2 LOW findings.

## Findings summary
| Sev | Item | Repair |
| LOW | `YetToGo.md` orphan scratch note, would be committed | link from README or move to docs/ / delete |
| LOW | `make test-frontend` / `typecheck` missing `##` help text | add `## ...` |
| LOW | `getHealth` in `frontend/lib/api.ts:131` unused export | wire or remove |
| LOW | `is_valid_event_id` `backend/app/schemas/event.py:107` unused | delete or use in events route/service |
| INFO | 0 commits yet: .env safety relies on `.gitignore` (verified) | commit `.gitignore` first |
No HIGH/MED findings. No repairs applied (audit is read-only).
