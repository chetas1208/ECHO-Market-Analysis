# Final test matrix

| Subsystem | Test/evidence | Result |
|---|---|---|
| DB | Clean Alembic migration and drift check | PASS |
| Events | API, seed idempotency, source evidence | PASS |
| Market | Replay/offline provider contracts and outage-safe status | PASS |
| World | Replay/offline mode cannot report LIVE | PASS |
| Graph | Seed validation and immutable snapshot tests | PASS |
| Cause | Cause/cluster/UNKNOWN tests | PASS |
| Forecast | Forecast availability, no-lookahead, model-status tests | PASS |
| Models | Optional bundle and Chronos runtime availability | DEGRADED — artifacts unavailable locally |
| Ledger | Append-only trigger and content-hash tests | PASS |
| Simulator | Deterministic replay simulation tests | PASS |
| Backtest | Frozen run artifact and API tests | PASS |
| Strategy | Risk, absorption, confirmation, and abstention gates | PASS |
| Paper execution | Replay dry-run and live-mode rejection | PASS |
| Alpaca paper | Credential/order verification | DEGRADED — credentials unavailable |
| UI | Vitest, lint, typecheck, production build | PASS |
| Demo | Reset target and deterministic replay package | PASS — local command path |
| Rolling 10D | Two-week analysis on historical evidence | UNAVAILABLE — synthetic fixture below threshold |
| Performance | Browser/API latency budget | UNAVAILABLE — no browser benchmark run |

Final counts: backend `1328 passed, 90 skipped, 0 failed`; frontend `163 passed,
0 failed`; frontend lint, typecheck, and production build passed.
