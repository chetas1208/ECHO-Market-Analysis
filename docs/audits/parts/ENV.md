# Shared environment notes for audit/implementation agents (ECHO)
- Repo: "/home/923873155/ECHO - Market Analysis" (quote the path).
- Docker: use the PRIVATE daemon: `export DOCKER_HOST=unix:///tmp/echo-dockerd/docker.sock`. Compose Postgres container `echo-db-1` is RUNNING on 127.0.0.1:5433 (user echo / pw echo_dev_password / db echo). Do NOT restart the daemon or the container; do NOT touch the shared daemon (~/.docker/run/docker.sock).
- psql: `docker exec echo-db-1 psql -U echo -d <db> -c "..."` (no local psql).
- uv: `export PATH=$HOME/.local/bin:$PATH`; backend commands from backend/ via `uv run ...`.
- Use your OWN database name (create with `docker exec echo-db-1 psql -U echo -d postgres -c "CREATE DATABASE <name>"`) and drop it when done. Never touch DBs `echo` or `echo_test` unless your task says so.
- Ports: use only the ports assigned in your task. Never `pkill -f` by pattern (kills your own shell); kill by PID.
- Playwright headless chromium: `SP=/tmp/claude-1989081997/-home-923873155-ECHO---Market-Analysis/0c10bd1e-c35c-4a8b-84fb-4a9c54968474/scratchpad; export LD_LIBRARY_PATH=$SP/lib:$(find $SP/lib -type d | tr '\n' ':')`; helper $SP/shot.py; chromium at /home/923873155/.cache/ms-playwright/chromium_headless_shell-1234/chrome-headless-shell-linux64/chrome-headless-shell
- No git commits. Caveman-terse reports. Evidence-driven: Check / Result / Evidence / Repair / Verification / Status.

## Backend test isolation (IMPORTANT)
- Pure market tests live in backend/tests/market/ and never touch the DB (conftest override). Run only YOUR test files: `cd backend && uv run pytest tests/market/test_<yours>.py -q`.
- If you need a DB, ALWAYS `export TEST_DATABASE_URL=postgresql+asyncpg://echo:echo_dev_password@localhost:5433/echo_<yourslug>_test` (name must end `_test`; unique to you) and drop it at the end. NEVER run the full suite unless your task says so, and never use the default echo_test.
- Other agents write sibling modules concurrently per docs/day2-contract.md. Import only your own modules + types/settings/base. If a sibling isn't there yet, code to the contract signature and unit-test your module alone (stub siblings inside your test). Don't edit files you don't own; list needed cross-file changes in your report.
- Lint only your files: `uv run ruff check <files> && uv run ruff format <files>`.
