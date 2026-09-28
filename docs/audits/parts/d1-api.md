# Day 1 audit: backend API (port 8110, db `audit_api`)

Setup: created `audit_api`; `alembic upgrade head` (0001 -> 0003, 5 tables) OK; seed created `evt_mock_hormuz_naval_001` (stored `WORLD`, served `world`). uvicorn on 127.0.0.1:8110 with DATABASE_URL set. Servers killed by PID, db dropped, 8110 free.

## Endpoint checks (healthy DB)

| Check | Result | Evidence |
|---|---|---|
| GET /api/v1/health | PASS 200 | `{"status":"ok"}` |
| GET /api/v1/ready | PASS 200 | `{"status":"ready","checks":{"database":"ok"}}` |
| POST /events valid | PASS 201 | body has all 19 fields; `timestamp` normalised to UTC; `source_type` lowercase |
| POST /events offset ts + `WORLD` | PASS 201 | `-05:00` -> `17:00:00Z`; uppercase accepted, returned `world`; id generated `evt_<12hex>` |
| GET /events | PASS 200 | `{items,total:2,limit:50,offset:0}`, ordered timestamp desc |
| GET /events?limit=1&offset=1 | PASS 200 | paging echoes limit/offset; total unchanged |
| GET /events/{id} | PASS 200 | same shape as list item |
| confidence=1.5 | PASS 422 | `{"error":{"code":"validation_error","message":"Request validation failed","request_id":..,"details":[{"loc":["body","confidence"],"msg":"Input should be less than or equal to 1","type":"less_than_equal"}]}}` |
| naive timestamp | PASS 422 | detail msg "timestamp must be timezone-aware: include a UTC offset or 'Z'..." |
| unknown id | PASS 404 | `{"error":{"code":"not_found","message":"Event 'evt_nope' not found","request_id":..}}` |
| duplicate id | PASS 409 | `{"error":{"code":"conflict","message":"Event 'evt_audit_001' already exists",..}}` |
| PUT / DELETE /events/{id} | PASS 405 | `allow: GET`, envelope code `method_not_allowed` |
| PUT /events | PASS 405 | `allow: POST` |
| unknown route | PASS 404 | envelope `not_found` |
| malformed JSON | PASS 422 | `json_invalid`, no payload echo |
| bad id pattern + extra field | PASS 422 | two detail entries (`string_pattern_mismatch`, `extra_forbidden`) |
| limit=0 | PASS 422 | `query.limit` |
| severity "NaN" | PASS 422 | `finite_number` |
| CORS preflight (Origin localhost:3000) | PASS 200 | allow-origin echoed, methods GET/POST/OPTIONS, X-Request-ID exposed/allowed |

X-Request-ID: client-supplied value echoed in header and in error envelope; absent header -> server generates 32-hex uuid.

## Logging
Stdout is one JSON object per line: `timestamp, level, service, logger, request_id, message` + `operation, method, path, status_code, duration_ms` (access) / `event_id` (events.create). Every request-scoped line carries `request_id` (e.g. `audit-rid-1`); only startup/seed lines (outside a request) have `request_id: null`. uvicorn's own access log is suppressed in favour of `echo.access`. PASS.

## DB-down (DATABASE_URL -> localhost:5999, fake password `SECRETpw_xyz`)
| Request | Status | Body |
|---|---|---|
| GET /health | 200 | `{"status":"ok"}` (liveness independent of DB, correct) |
| GET /ready | 503 | `{"status":"not_ready","checks":{"database":"error"}}` (~17 ms) |
| GET /events, GET /events/{id}, POST /events | 503 | `{"error":{"code":"database_error","message":"The database is unavailable","request_id":"fail-rid-N"}}` (~10 ms) |

- Response bodies: no stack trace, no SQL, no DSN/host/port/credentials. PASS.
- Server log: `ERROR echo.errors "database error"` with request_id and a stack trace in the `exception` field (137-163 lines, ends `ConnectionRefusedError: [Errno 111]`). grep of whole log for `SECRETpw` and `password` = 0 hits, so no credential leak. Full traceback in server logs is normal, but verbose at ERROR (per request; no rate-limit).
- App starts and stays up with unreachable DB (engine lazy). PASS.
- Not tested: recovery after the DB returns (engine has `pool_pre_ping=True`, expected fine).

## Frontend type comparison (types/event.ts, types/api.ts, lib/api.ts)
- `EchoEvent` vs Event JSON: all 19 keys match by name and type (`summary: string|null`, arrays, `economic_channels: Record<string,number>`, `metadata`, `is_mock`, `created_at`, `ingested_at`); no extra or missing keys. `SourceType` union matches API lowercase.
- `Paginated<T>` = `{items,total,limit,offset}` matches. `HealthResponse`, `ReadyResponse` match on 200.
- Error envelope `{error:{code,message,request_id,details?}}` matches `ApiErrorEnvelope`.

Mismatches (both LOW):
1. `ApiErrorCode` lacks `"method_not_allowed"` (emitted for every 405) and the fallback `"http_error"` (other HTTP statuses). Runtime passes the string through unchanged so nothing breaks, but the TS union is incomplete. Repair: add both codes to `ApiErrorCode` in frontend/types/api.ts.
2. `/ready` 503 body is `{"status":"not_ready","checks":...}` (not the error envelope). `lib/api.ts request()` treats every non-2xx as an error and only accepts the envelope, so `getReady()` throws `ApiError{code:"unknown_error", message:"Unexpected response from API (HTTP 503)"}` and never resolves to `ReadyResponse{status:"not_ready"}`; the `"not_ready"` union member is effectively dead. Impact: AppShell already maps any non-success to DEGRADED, so UI behaviour is correct, but the reason (database down) and the detailed `checks` are lost. Repair (optional): in `getReady`, special-case 503 with a `status` field and return the body.

Also noted (info): 503 responses carry no `Retry-After`; ready failure responses carry no request_id in the body (header still present).

## Status
Backend API contract: PASS on all 13 requested checks and DB-down behaviour. 2 low-severity frontend-type mismatches, no repairs applied (audit only).
