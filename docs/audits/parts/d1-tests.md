# D1 automated validation (2026-09-20)
Env: compose PG 127.0.0.1:5433 (echo-db-1). uv at ~/.local/bin. pnpm 11.23.0.

## Backend (cd backend/)
| Check | Command | Result | Evidence |
|---|---|---|---|
| Tests | `uv run pytest -q` | PASS | `134 passed in 33.18s` (rerun with -rs: 134 passed in 32.99s; 0 failed, 0 skipped, 0 xfail, no warnings shown) |
| Lint | `uv run ruff check .` | PASS | `All checks passed!` |
| Format | `uv run ruff format --check .` | PASS | `49 files already formatted` |
| Dep consistency | `uv pip check` | PASS | `Checked 36 packages ... All installed packages are compatible` |
| Lock in sync | `uv lock --check` | PASS | `Resolved 38 packages` (no drift error) |

Key versions: fastapi 0.141.1, sqlalchemy 2.0.54, asyncpg 0.31.0, alembic 1.20.0, pydantic 2.13.5, pytest 9.1.1, pytest-asyncio 1.4.0, ruff 0.16.8, uvicorn 0.53.0.

Note: after tests, DBs `echo_test` and `echo_migrations_test` still exist in PG (also `audit_ui` from another agent). Test DBs are persisted between runs (not dropped at session end); harmless but leaves state.

## Frontend (cd frontend/)
| Check | Command | Result | Evidence |
|---|---|---|---|
| Install | `pnpm install --frozen-lockfile` | PASS | `Already up to date` (lockfile consistent) |
| Typecheck | `pnpm typecheck` | PASS | `tsc --noEmit`, no errors |
| Lint | `pnpm lint` | PASS | `eslint .`, no output/errors |
| Unit tests | `pnpm test` | PASS | vitest 5.0.1: `Test Files 1 passed (1)`, `Tests 6 passed (6)` |
| Build | `pnpm build` | PASS | Next 16.3.5 Turbopack, compiled, TS ok, 8/8 static pages; no .next conflict, no retry. Routes: / ○, /_not-found ○, /events ƒ, /events/[id] ƒ, /forecasts ○, /graph ○, /icon.svg ○, /strategy ○ |
| Dep sanity | `pnpm ls --depth 0` | PASS | 14 pkgs, no missing/extraneous/invalid: next 16.3.5, react/react-dom 19.3.0, ts 5.9.3, eslint 9.39.5, vitest 5.0.1, jsdom 30.1.0, @testing-library/react 16.3.3 |

## Observations
- Frontend has only 1 test file / 6 tests: thin coverage vs. 6 routes (no tests for pages/lib beyond that file).
- Everything green; no repairs needed.

Status: ALL PASS (backend 134/134, frontend 6/6, lint/format/typecheck/build clean).
