# ECHO Reference Repositories

Third-party repositories ECHO integrates with, studies, or may revisit later. This file is the
single register: what each repo is for, what we take from it, and what we deliberately do not.

Facts below were read from shallow clones on **2026-09-20** (`scripts/fetch_reference_repos.sh`).
"Last inspected" is the `HEAD` commit of that clone. The clones are `--depth 1`, so no tags are
available; versions come from `pyproject.toml` / `package.json` / `version.json` where stated.
Re-inspect before building on a finding, since upstreams move fast.

## Policy

1. **Do not vendor.** No copied source trees, no git submodules, no subtrees. Clones live in
   `.reference-repos/` (gitignored) and are fetched on demand by `scripts/fetch_reference_repos.sh`.
   App startup, `make`, and CI never fetch them.
2. **Reference is not dependency.** Studying a repo does not make it part of the application.
   Only Tier 1 packages that are *explicitly* adopted (official PyPI/npm package, pinned version)
   appear in `pyproject.toml`. Tier 2 and Tier 3 never do.
3. **Adapter rule.** Third-party SDK object -> ECHO adapter -> ECHO domain object. SDK types
   (`massive.websocket.models.EquityAgg`, `alpaca.data.models.Bar`, World Monitor JSON, ...) never
   leave the adapter module and never appear in the database schema, API, or UI.
4. **ECHO-owned interfaces.** Adapters implement interfaces ECHO defines:
   - `MarketDataProvider` — implementations `Massive` (primary), `Alpaca` (secondary/fallback)
   - `WorldEventProvider` — implementation `WorldMonitor`
   - `ExecutionProvider` — implementation `AlpacaPaper`

   Swapping a vendor must only touch its adapter.
5. **Licensing rule.** Inspect the license file before copying *any* code or text. Prefer the
   official published package over copying. If a snippet is ever copied, preserve the copyright
   and license header and record it in this file. Copyleft licenses (AGPL, LGPL) need extra care:
   see the per-repo notes. This is engineering guidance, not legal advice.
6. **No secrets in the repo.** API keys go in `.env` (gitignored); see `.env.example`.

## Environment integration boundary (2026-09-21)

The workspace contains shallow reference clones for `worldmonitor`,
`massive-client-python`, and `alpaca-py` under `.reference-repos/`. They are
not runtime dependencies and are never imported by the application. The
official Massive Python package and Alpaca SDK are the runtime adapters;
World Monitor is called through ECHO's existing REST/MCP adapter.

An AURE/Aurora checkout exists outside this repository. Inspection confirmed a
real `aure` CLI with `init`, `info`, `db check`, `query`, `serve`, and stdio
`mcp` commands. ECHO only uses the read-only `db check` command for validation.
`AURE_BINARY`, `AURE_DATABASE_PATH`, and `AURE_ENABLED` must be supplied by an
operator before AURE becomes active; otherwise the bounded deterministic graph
path remains active through the explicit NetworkX-compatible fallback. Cloning
any of these repositories does not provide hosted credentials or quota.

## Summary

| Tier | Repo (clone dir) | Role in ECHO | Status | Milestone | License |
|------|------------------|--------------|--------|-----------|---------|
| 1 | koala73/worldmonitor (`worldmonitor`) | Primary external-world intelligence | Adapter implemented; hosted REST/MCP remains credential-gated | Day 3 | AGPL-3.0-only (`sdk/`, `cli/` are MIT) |
| 1 | massive-com/client-python (`massive-client-python`) | Primary live market feed | Official client adapter implemented; hosted data remains key-gated | Day 2 | MIT |
| 1 | alpacahq/alpaca-py (`alpaca-py`) | Secondary market data, paper execution, account state | Data fallback and paper adapter implemented; paper credentials remain required | Day 2 (data), Day 9 (paper execution) | Apache-2.0 |
| 2 | nautechsystems/nautilus_trader (`nautilus-trader`) | Architecture reference only | Not integrated, not a dependency | n/a | LGPL-3.0 |
| 2 | QuantConnect/Lean (`lean`) | Architecture reference only | Not integrated, not a dependency | n/a | Apache-2.0 |
| 3 | ib-api-reloaded/ib_async (`ib-async`) | Possible future IBKR access | Not integrated | none scheduled | BSD-2-Clause |
| 3 | Voyz/ibind (`ibind`) | Possible future IBKR access | Not integrated | none scheduled | Apache-2.0 |

Fetch: `scripts/fetch_reference_repos.sh` (all) or e.g. `scripts/fetch_reference_repos.sh alpaca-py worldmonitor`.
`--update` fast-forwards existing clones; `--list` prints the names.

---

# Tier 1 — Integrations

## koala73/worldmonitor

| Field | Value |
|-------|-------|
| Upstream | https://github.com/koala73/worldmonitor |
| Role in ECHO | Primary external-world intelligence source (decision D-008) behind `WorldEventProvider` |
| Integration status | Adapter implemented at `backend/app/world/providers/worldmonitor.py`; it consumes the documented network API only (REST and/or MCP over ECHO's own `httpx` client). Runtime wiring is in `backend/app/world/runtime.py`. Never fork, embed, or vendor its frontend, server or SDK source. |
| Milestone | Day 3 |
| License | **AGPL-3.0-only** for the app/server (`LICENSE`, `package.json` `"license": "AGPL-3.0-only"`, `docs/license.mdx`). **MIT** for the thin clients: `cli/` (`cli/LICENSE`, `cli/package.json` 0.1.3), `sdk/python` (`sdk/python/LICENSE`, `pyproject.toml` `license = "MIT"`, `worldmonitor-sdk` 0.1.1), `sdk/go`, `sdk/ruby` (each with its own `LICENSE`). Hosted-service data use is governed separately by the EULA (`docs/eula.mdx` section 5), not by the AGPL. |
| Last inspected | `977161b` (committer date 2026-09-20T22:24:13+04:00), package version 2.10.0. `git pull --ff-only` on 2026-09-20 was a no-op (before = after = `977161b`); the earlier `4cb7fc1` note in this file was from a previous shallow clone and is superseded. |

**What we use:** its published network surfaces only: REST (`https://api.worldmonitor.app`, OpenAPI in
`docs/api/*.openapi.{json,yaml}`) and the MCP server (Streamable HTTP JSON-RPC; canonical URL
`https://api.worldmonitor.app/mcp`, `https://worldmonitor.app/mcp` proxies the same handler,
`docs/mcp-overview.mdx`). ECHO calls them with **its own `httpx` client**; no World Monitor source is
copied, and the MIT `worldmonitor-sdk` is **not** a dependency (it is synchronous `urllib`; useful only as a
reading reference for headers/paths). Data is normalized into ECHO canonical events; raw payloads stay
traceable in `source_refs`.

**What we do not use:** its web app, Tauri desktop app, map/globe UI, Convex/Clerk/Vercel stack,
Docker/self-host files, or any copied source. We do not run a World Monitor server.
AGPL notes: we only make network calls to the hosted API, so no AGPL source is included in or linked
into ECHO. Copying or modifying anything from the AGPL portion would impose AGPL obligations on ECHO, so do not.
`docs/license.mdx` also states official branding needs separate permission (trademark policy): do not present its
name/logo in the UI as if it were ours; a plain provider label ("World Monitor") is attribution, not branding.
This is engineering guidance, not legal advice.

**Important paths:** `api/mcp.ts`, `api/mcp/registry/cache-tools.ts` (tool definitions and JSON schemas),
`sdk/python/src/worldmonitor_sdk/__init__.py`, `cli/src`, `docs/mcp-quickstart.mdx`, `docs/mcp-overview.mdx`,
`docs/mcp-tools-reference.mdx`, `docs/mcp-error-catalog.mdx`, `docs/usage-rate-limits.mdx`, `docs/api-keys.mdx`,
`docs/pricing.mdx`, `docs/eula.mdx`, `docs/source-attribution.mdx`, `docs/data-sources.mdx`,
`docs/api/NewsService.openapi.json`, `docs/api/ConflictService.openapi.json`, `proto/worldmonitor/*`,
`api/_product-catalog.generated.js` (plan limits as code), `scripts/seed-insights.mjs` (news digest payload).

### Findings for Day 3 (verified against `977161b`)

**1. Interfaces ECHO calls (implemented adapter surface).**
- Primary, one call per poll: MCP `tools/call` `get_news_intelligence` (arguments used: `limit`, optional
  `min_importance`, `category`, `alerts_only`; every tool also accepts `jmespath` to project server-side).
  Returns cached `insights.topStories[]`, `gdelt-intel`, `cross-source-signals` (`docs/mcp-tools-reference.mdx`,
  `api/mcp/registry/cache-tools.ts` ~L993). Cache read, sub-second, 1 unit per call.
- Optional structured-event slices (each costs another call, so opt-in only): `get_conflict_events`
  (UCDP / Iran / unrest events, has coordinates), `get_chokepoint_status`, `get_supply_chain_data`,
  `get_natural_disasters`, `get_cyber_threats`, `get_sanctions_data`, `get_energy_intelligence`; all `free-account`
  access, cache reads. Not used by default: `get_maritime_activity`, `get_signal_convergence`, `get_hotspot_escalation`,
  `get_intel_timeline`, `get_similar_events`, `get_alert_digest`, `get_world_brief` (all `subscription` access; the
  first is a live RPC, weight 2 on API plans).
- Free discovery: `get_sources` (no credentials, no quota) and `tools/list` / `describe_tool` (no daily quota).
- REST alternative for headlines: `GET https://api.worldmonitor.app/api/news/v1/list-feed-digest?variant=full|tech|finance|happy|commodity`
  returns `NewsItem[]` with `link`, `source`, `publishedAt`, `location{latitude,longitude}`, `locationName`, `threat`,
  `importanceScore`, `credibilityScore`, `corroborationCount`, `snippet` (`docs/api/NewsService.openapi.json`). Needs a key.
  REST paths for the conflict slices: `/api/conflict/v1/list-ucdp-events`, `/api/conflict/v1/list-iran-events`,
  `/api/unrest/v1/list-unrest-events`. `.env`/settings: `WORLD_MONITOR_API_KEY`, `world_monitor_base_url`
  (default `https://api.worldmonitor.app`, confirmed correct as the REST base; the MCP URL is that base + `/mcp`).

**2. Authentication.**
- Header `X-WorldMonitor-Key: wm_...` (alias `X-Api-Key`) on both REST and MCP (`api/_api-key.js`,
  `docs/mcp-quickstart.mdx`). Do **not** send it as `Authorization: Bearer` (fails with `401 invalid_token`).
  OAuth 2.1 (`Authorization: Bearer`, access token 1 h, refresh 7 d) is the other door but is browser-consent based
  and unsuitable for a headless ECHO worker.
- Key acquisition: dashboard Settings > API Keys (`docs/api-keys.mdx`); **only API Starter (USD 99.99/mo) and API
  Business** can create `wm_` keys. **Pro and Pro Business have no manual key (OAuth only)** (`docs/pricing.mdx`).
- Anonymous: only `get_sources`, `tools/list`, `initialize`/`ping`/metadata methods. Every data tool needs a credential
  (`free-account` = signed-in free account via OAuth, `subscription` = paid). Set a real `User-Agent`: the API edge's WAF
  challenges generic UAs (python-urllib, python-requests, curl, empty) (`sdk/python/.../__init__.py` L34); httpx's default
  UA is at risk, so ECHO must send its own (e.g. `echo-market-analysis/<ver>`).
- No key configured -> ECHO state `UNCONFIGURED` (see 6); never block startup.

**3. Rate limits and quotas** (`docs/usage-rate-limits.mdx`, `docs/mcp-overview.mdx`, `docs/mcp-error-catalog.mdx`,
`api/_product-catalog.generated.js`):

| Plan | MCP daily | Per-minute (per user) |
|------|-----------|-----------------------|
| Free account (OAuth only) | 5 calls and 3 idle-gap windows / UTC day, `free-account` tools only | anonymous ceilings: 10/min/IP `get_sources`, 60/min/IP discovery |
| Pro | 50 calls / UTC day (OAuth only, no key) | 60 |
| Pro Business | 250 calls / UTC day (OAuth only, no key) | 60 |
| API Starter (`wm_` key) | 1,000 units / UTC day shared with REST | 60 |
| API Business (`wm_` key) | 10,000 units / UTC day shared with REST | 300 |
| Enterprise | unlimited | 1,000 |

- Units on API plans: cached read = 1 (`get_news_intelligence`, `get_conflict_events`, `get_chokepoint_status`), live downstream = 2
  (`get_country_risk`, `get_wto_trade_flows`, `search_intel_history`), `get_country_brief` = 3, `get_airspace` = 5.
  `tools/list` / `describe_tool` entries expose the price at `_meta["worldmonitor/weight"]`. `get_sources` and `describe_tool` are free.
  Default REST limiter for unauthenticated `/api/*` is 600/min/IP; sliding 60 s windows; day resets 00:00 UTC.
- 429 / `Retry-After`: daily cap, free allowance, anonymous ceiling and key-validation floods return **HTTP 429**, JSON-RPC
  error `-32029`, `Retry-After` = seconds until next UTC midnight (daily) or a short value. The **per-minute throttle returns
  `-32029` inside HTTP 200 with NO 429**: the adapter must inspect the JSON-RPC `error.code`, not only the HTTP status;
  back off ~1 s (sliding window). `503` + `-32603` carries `Retry-After: 5` (or a dynamic 1-60 s with `X-Billing-Verification`
  during subscription re-verification): honour the header. Other codes: `-32001`/401 auth (with `WWW-Authenticate`), `-32002`/403
  `upgrade-required`. Exhausted quota is deliberately not 401. A downstream-429 keeps the daily reservation charged.
- Poll budget check at ECHO's default 1800 s interval: 48 calls/day of `get_news_intelligence` alone, which fits API Starter
  (1,000) comfortably and would consume ~96% of a Pro 50/day cap if one call per poll (not reachable with a key anyway). Adding
  N optional slices multiplies that by N+1.

**4. Response fields for ECHO's normalizer** (`get_news_intelligence`, `insights.topStories[]`; MCP payload is a text block whose
`text` is JSON `{cached_at, stale, data:{...}}`; parse `text` then take `data`):

| Field | Notes |
|-------|-------|
| `primaryTitle` -> `headline` | string |
| `primarySource` -> `source_name`; `sources[]` (outlet names, tier-sorted, deduped) | strings |
| `primaryLink` -> `source_url` | URL |
| `pubDate` | **epoch milliseconds (number) or an ISO string** when the feed only had a text date; handle both, normalize to UTC-aware |
| `lastUpdated` | string, timestamp of newest article in the cluster |
| `memberTitles[]` | every clustered headline, primary first |
| `category` | free string (`conflict`, `economy`, `cyber`, ...; fallback `general`; legacy keyword categories: `violence`, `unrest`, `geopolitical`, `crisis`, `natural_disaster`, `political`, `economic`) |
| `threatLevel` | string: `critical`/`high`/`medium`/`low`/`info` from the digest; legacy keyword fallback also emits `elevated`/`moderate` (`scripts/seed-insights.mjs` L99-106, L711-726). Not a fixed enum in the MCP schema |
| `countryCode` | ISO alpha-2 or null; **extracted from the headline text, heuristic** |
| `importanceScore` / `effectiveImportanceScore` / `upstreamImportanceScore` | integers, base 0-100 but **can exceed 100 (approx. cap 138)** (`proto/.../news_item.proto`); do not clip-assume 0-100 |
| `credibilityScore` | 0-100 source reliability (optional key; absent when not finite); state-controlled media capped at 40 |
| `uniqueSourceCount` | distinct publishers (corroboration breadth); `sourceCount` = raw article count; `corroborationSourceCount` = entity-gate corroborators, 0 when the gate did not fire; `entityCorroboration` bool |
| `sourceTier` | number, best (lowest) tier in cluster, 1 = wire/primary |
| `isAlert` bool; `velocity{level,sourcesPerHour}` (currently a constant `normal`/0 placeholder: ignore) | |
| `sourceProvenance{risk: low|medium|high|unknown, type: wire|gov|intel|mainstream|market|tech|other|unknown, ...}` | |

- **Coordinates:** **NOT provided on `get_news_intelligence` top stories** (only `countryCode`). Coordinates exist on the REST
  `list-feed-digest` `NewsItem.location{latitude,longitude}` + `locationName`, on UCDP events (`location`, `country`,
  `dateStart`/`dateEnd` epoch, `deathsBest`), ACLED events (`location`, `occurredAt` epoch, `fatalities`) and Iran events
  (`latitude`, `longitude`, `locationName`, ISO-string `timestamp`, `sourceUrl`), and on unrest events. ECHO must leave `latitude`/`longitude`
  as `None` (GeoInfo `resolved=False`) for news items and resolve country via its own `geo.py` when only a code/name exists.
- No event id on `topStories`: derive `provider_event_id` as a stable hash of `primaryLink` (fallback `primaryTitle`+`pubDate`).
- ECHO's `severity`, `corroboration`, `confidence`, `novelty` remain **derived** by our normalizer (corroboration from
  `uniqueSourceCount`/`corroborationSourceCount`, confidence from `credibilityScore`/`sourceTier`, `provider_scores` from the
  importance fields); World Monitor emits none of ECHO's schema. Keep the full raw item in `source_refs.metadata`.

**5. Freshness and latency.** Cache-backed reads, "typically 300-800 ms" (`docs/mcp-quickstart.mdx`); `get_news_intelligence` slice
freshness budgets: news insights **30 min**, GDELT intel **45 min**, cross-source signals **60 min**; top-level `stale` flag is true
if any slice exceeds its budget and `cached_at` is the oldest contributing timestamp. Other slices: UCDP 30 min, unrest 2 h,
chokepoint live transits 30 min, natural disasters 30 min, cyber 4 h, sanctions 1 d, supply chain 2 d. Free-tier dashboard refresh
is "typically 5-15 minutes". Polling faster than ~30 min therefore returns mostly identical data and burns quota; the 1800 s default
matches the 30 min news budget. Live LLM tools (`analyze_situation`, `get_country_brief`) take 1-4 s and are not used.
The digest is a **live window**, not a history (`query` filters only the current window); backfill needs `search_intel_history`
(subscription, weight 2).

**6. ECHO fallback behavior** (`backend/app/world/settings.py`, `providers/base.py`, `docs/day3-contract.md`):
`echo_world_provider` in `off | replay | world_monitor` (default `off`); `echo_world_poll_interval_s` default **1800.0** (WM quota is
small); no key -> `world_monitor_configured` false -> state `UNCONFIGURED`, mode `OFFLINE`, startup never blocked;
`ReplayWorldEventProvider` (fixtures, `is_replay=True`, provider `"replay"`, mode `REPLAY`) is the demo/CI fallback and must never
masquerade as LIVE (D-031); on 429/503/network error the provider keeps serving the **last cached response** and reports
`DEGRADED`/`STALE` via `health()` (states `HEALTHY|DEGRADED|STALE|ERROR`), honouring `Retry-After` in `stream()`; malformed items are
skipped and counted, never raised. `stale: true` from World Monitor should map to `DEGRADED`, not `HEALTHY`.

**7. Data terms** (`docs/eula.mdx` section 5, `docs/pricing.mdx`): headlines + publisher + URL + up to 200 chars of text are class **R3:
display and cache allowed, 30-day retention, source attribution must remain**; structured events (what/where/when/type/severity, no source text)
are R2 and derived scores R1 (indefinite retention). API Starter is a commercial license for **internal** use; showing outputs to customers
needs API Business. ECHO should store headline/link/publisher (R3) with a 30-day retention/purge policy and keep attribution in `source_refs`;
do not store full article bodies. `snippet` is capped at 400 chars upstream but R3 limits stored text to 200.

**8. Contradictions with earlier assumptions in this file (corrected above).**
- "Only `get_sources` works without a key; all other data tools need a subscription": partly wrong. Anonymous = `get_sources` only, but
  `get_news_intelligence`, `get_conflict_events`, `get_chokepoint_status` etc. are `free-account` (a signed-in free account, OAuth, gets 5 calls/day);
  the truly `subscription`-gated ones are `get_maritime_activity`, `get_signal_convergence`, `get_hotspot_escalation`, `get_intel_timeline`,
  `get_similar_events`, `get_alert_digest`, `get_world_brief`.
- "50 calls/day on Pro with an API key": wrong pairing. Pro is OAuth-only and has no `wm_` key; a key requires **API Starter or Business**
  (1,000 / 10,000 units/day shared with REST). Upstream `docs/mcp-quickstart.mdx` still says API Starter/Business "use the 50/day default"; that
  contradicts `docs/mcp-overview.mdx`, `docs/usage-rate-limits.mdx`, `docs/mcp-error-catalog.mdx`, `docs/pricing.mdx` and the code
  (`api/_product-catalog.generated.js`, `mcpDailyBudgetSharedWithRest: true`), so treat the quickstart as stale but re-verify on the first paid call
  via the exempt resource `worldmonitor://account/mcp-allowance`.
- Per-minute limit is **HTTP 200 + `-32029`**, not a 429, so status-code-only retry logic misses it.
- "Importance/credibility 0-100": only `credibilityScore` is 0-100; `importanceScore` can reach ~138.
- "Python SDK is a possible client": the decision is now our own `httpx` client (the SDK is sync urllib and would need a thread); the SDK stays
  a reading reference only. Tool name list in the old note was complete; `get_alert_digest`/`get_intel_timeline` etc. are subscription-only.
- ACLED `AcledConflictEvent` shape in the old note is correct for REST `list-acled-events`, but the MCP `get_conflict_events` tool serves UCDP/Iran/unrest slices instead.
- Unresolved/unverified: exact JSON of `get_conflict_events`/`get_chokepoint_status` payloads was read from docs/OpenAPI only, not from a live call
  (no key available here), so field names beyond News/UCDP/ACLED/Iran schemas must be confirmed against a real response before the adapter is finalized.

## massive-com/client-python

| Field | Value |
|-------|-------|
| Upstream | https://github.com/massive-com/client-python |
| Role in ECHO | Primary live market-data stream (D-007) behind `MarketDataProvider` (Massive impl) |
| Integration status | Not yet integrated. Use the **official client** as a normal pinned dependency inside the Massive adapter only. |
| Milestone | Day 2 |
| License | **MIT** (`LICENSE`; `pyproject.toml` `license = "MIT"`) |
| Last inspected | `481e5c2` (2026-07-09). Package `massive`, Python `^3.9`, deps `urllib3`, `websockets>=14`, `certifi` |

**What we use:** `pip install massive` (`WebSocketClient` for live aggregates, `RESTClient` for
historical bars / backfill). The company formerly known as Polygon.io rebranded to Massive on
2025-10-30; API base `https://api.massive.com`, WS host `socket.massive.com`, and existing keys keep working.

**What we do not use:** copied code, its example scripts as app code, Launchpad/Business feeds,
options/crypto/forex/futures markets (out of scope), and the SDK's model classes outside the adapter.

**Important paths:** `massive/websocket/__init__.py` (client), `massive/websocket/models/models.py`
(message classes), `massive/websocket/models/common.py` (`Feed`, `Market`, `EventType`),
`massive/rest/aggs.py` + `massive/rest/models/aggs.py` (bars), `massive/rest/base.py`,
`examples/websocket/{stocks-ws.py,async.py,raw.py}`, `test_websocket/{mock_server.py,test_conn.py}`
(a mock WS server useful for our own reconnect tests), `massive/exceptions.py`.

### Findings for Day 2
- **Client shape.** `WebSocketClient(api_key=os.getenv("MASSIVE_API_KEY"), feed=Feed.RealTime, market=Market.Stocks, raw=False, max_reconnects=5, subscriptions=[...], custom_json=None)`.
  Raises `AuthError` if no key. Note: the `api_key` default is read from the environment **at import time**,
  so pass `api_key=` explicitly from ECHO settings.
- **Run modes.** `client.run(handle_msg)` is blocking (`asyncio.run` inside). For an asyncio service use
  `await client.connect(processor)` where `processor` is an `async def` taking `List[WebSocketMessage]`;
  `client.unsubscribe_all()` and `await client.close()` stop it (`examples/websocket/async.py`).
- **Subscribe API.** `client.subscribe("AM.TSLA", "AM.NVDA")` with topic strings `<EV>.<SYMBOL>`; `*` for all.
  Subscriptions are *scheduled* and reconciled inside the connect loop, and are re-applied automatically
  after a reconnect.
- **Aggregates.** `A.<sym>` = per-second aggregates, `AM.<sym>` = per-minute aggregates (`EventType.EquityAgg` = "A",
  `EquityAggMin` = "AM"). There is no native 5m/15m stream: build 5m/15m bars from 1m locally
  (or from REST `RESTClient.list_aggs(ticker, multiplier, timespan, from_, to)` for backfill).
- **Message model.** `EquityAgg` fields: `event_type, symbol, volume, accumulated_volume, official_open_price, vwap,
  open, close, high, low, aggregate_vwap, average_size, start_timestamp, end_timestamp, otc`
  (wire keys `ev, sym, v, av, op, vw, o, c, h, l, a, z, s, e`). Timestamps are integers (Unix ms). Fields are all
  `Optional`, so the adapter must validate before building an ECHO `MarketObservation`.
  Trades = `T.*`, quotes = `Q.*`. Status messages (`ev == "status"`) are filtered inside the client.
- **Reconnect behavior.** On `ConnectionClosedError` the client retries up to `max_reconnects` (default 5)
  and then re-raises the last error, so ECHO needs its own outer supervisor (backoff + alerting) for
  "live data remains connected". `AuthError` is raised if the auth handshake returns `auth_failed`.
- **Feeds.** `Feed.RealTime = socket.massive.com`, `Feed.Delayed = delayed.massive.com`. Which one works
  depends on the account plan; the README notes free-tier rate limits. Make feed a config value.
- **REST bars.** `Agg` fields `open, high, low, close, volume, vwap, timestamp, transactions, otc`
  (`o,h,l,c,v,vw,t,n`). `list_aggs` paginates as an iterator; `get_aggs` returns one page. Retries 413/429/5xx by default.

### Day 2 inspection (Massive)
- **Day 2 integration status: adapters implemented behind ECHO MarketDataProvider** (Massive = primary per D-007; SDK
  objects confined to the adapter module). Note: at time of writing only `providers/alpaca.py` was present in
  `backend/app/market/providers/`; confirm the Massive adapter file has landed before relying on this line.
- **Versions.** Installed `massive` 2.8.0 (backend lockfile; verified with `importlib.metadata`). Upstream inspected at
  `481e5c2` (2026-07-09); its `pyproject.toml` says `version = "0.0.0"`, so treat 2.8.0 as authoritative.
- **Constructor** (`massive/websocket/__init__.py:21`): `WebSocketClient(api_key=os.getenv("MASSIVE_API_KEY"), feed=Feed.RealTime,
  market=Market.Stocks, raw=False, verbose=False, subscriptions=None, max_reconnects=5, secure=True, custom_json=None, **kwargs)`.
  The `api_key` default is evaluated at import time; `None` raises `AuthError`. URL = `wss://<feed>/<market>`.
- **Subscribe strings.** `client.subscribe("AM.AAPL", ...)` (l.226) adds to `scheduled_subs`; `X.*` wildcard drops per-symbol
  subs of that topic. `unsubscribe_all()` is synchronous; `close()` is `async`. `Feed` (`models/common.py`) also has
  `Delayed="delayed.massive.com"`, `RealTime="socket.massive.com"`, plus Nasdaq/Launchpad/Business variants we do not use.
- **`EquityAgg`** (`massive/websocket/models/models.py:7`): `event_type, symbol, volume, accumulated_volume, official_open_price,
  vwap, open, close, high, low, aggregate_vwap, average_size, start_timestamp, end_timestamp, otc, fractional_volume,
  fractional_accumulated_volume` (wire `ev,sym,v,av,op,vw,o,c,h,l,a,z,s,e,otc,dv,dav`). All `Optional`; `s`/`e` are Unix ms ints;
  the two `fractional_*` fields are strings (`dv`/`dav`). `EventType.EquityAgg="A"`, `EquityAggMin="AM"` (`models/common.py:39-40`).
- **Run/reconnect** (l.79-196). `connect(processor, close_timeout=1)` is the awaitable loop; `run()` wraps it in `asyncio.run`.
  `ConnectionClosedError` increments `reconnects`, re-queues `self.subs` into `scheduled_subs`, and after
  `reconnects > max_reconnects` (default 5) re-raises; `ConnectionClosedOK` returns silently. `max_reconnects=None` retries forever.
  Status messages (`ev=="status"`) are logged at debug and dropped. Hence ECHO wraps `connect()` in its own supervisor
  (`providers/supervisor.py`, `backoff.py`) for "live data remains connected".

## alpacahq/alpaca-py

| Field | Value |
|-------|-------|
| Upstream | https://github.com/alpacahq/alpaca-py |
| Role in ECHO | Secondary market-data validation/fallback, paper execution, portfolio/account state (D-009). Never the only market source. |
| Integration status | Not yet integrated. Official package as a pinned dependency inside Alpaca adapters only. |
| Milestone | Day 2 (data fallback); Day 9 (paper execution and account state) |
| License | **Apache-2.0** (`LICENSE`, `pyproject.toml`; Copyright 2022 Alpaca) |
| Last inspected | `232179c` (2026-09-15). Package `alpaca-py`, Python `^3.10` |

**What we use:** `StockDataStream` / `StockHistoricalDataClient` (data), `TradingClient` and
`TradingStream` (paper orders, account, positions) via `AlpacaPaper` / `Alpaca` adapters.

**What we do not use:** the Broker API (`alpaca/broker`, for building brokerages), crypto/options
(out of scope for now), example bots and notebooks as app code, and **live-money trading**
(`paper=True` only; risk engine remains deterministic per D-020).

**Important paths:** `alpaca/data/live/stock.py` (`StockDataStream`), `alpaca/data/live/websocket.py`
(`DataStream` base, reconnect/backoff), `alpaca/data/historical/stock.py`, `alpaca/data/models/bars.py`,
`alpaca/trading/client.py` (`TradingClient`), `alpaca/trading/stream.py` (`TradingStream`),
`alpaca/trading/requests.py` (order request models), `alpaca/common/enums.py` (`BaseURL`), `examples/stocks/`.

### Findings for Day 2 (data) and Day 9 (execution)
- **Auth.** Every client needs `api_key` + `secret_key` (`.env.example` reserves `ALPACA_API_KEY`,
  `ALPACA_API_SECRET`, `ALPACA_PAPER=true`).
- **Live bars.** `StockDataStream(api_key, secret_key, raw_data=False, feed=DataFeed.IEX, data_timeout=None)`.
  Default feed is **IEX** (free); **SIP** requires a subscription. Subscribe with async handlers:
  `stream.subscribe_bars(handler, "AAPL", "MSFT")` (minute bars), also `subscribe_trades`, `subscribe_quotes`,
  `subscribe_updated_bars`, `subscribe_daily_bars`, `subscribe_trading_statuses`; `"*"` = all symbols.
  Handlers **must be coroutines** (`_ensure_coroutine`).
- **Run model.** `stream.run()` blocks (`asyncio.run(self._run_forever())`, stops on `KeyboardInterrupt`).
  It is built for its own event loop, so run it in a dedicated thread/process, or drive the internal
  `_run_forever()` coroutine (private API; avoid unless required). `stop()` is thread-safe.
- **Reconnect.** Built in: exponential backoff 1s to 30s (`_reconnect_min_backoff/_max_backoff`), and an
  opt-in `data_timeout` for "connected but mute" sockets (only enable for busy symbol sets).
- **Bar model** (`alpaca.data.models.Bar`): `symbol, timestamp (datetime, bar open), open, high, low, close, volume,
  trade_count, vwap, exchange`. Different field names and timestamp semantics from Massive's `EquityAgg`
  (Unix-ms start/end): the two adapters must converge on one ECHO bar type with explicit UTC bar-start/bar-end.
- **Historical.** `StockHistoricalDataClient.get_stock_bars / get_stock_quotes / get_stock_trades / get_stock_latest_bar / get_stock_snapshot`.
- **Execution (Day 9).** `TradingClient(api_key, secret_key, paper=True)`: `submit_order(OrderRequest)`, `get_orders`,
  `get_all_positions`, `get_account`, `get_clock`, `get_portfolio_history`, `close_all_positions`.
  `TradingStream(paper=True).subscribe_trade_updates(handler)` for fills. Use `client_order_id` and record every
  order/fill as an append-only row (see forecast/trade immutability decisions).

### Day 2 inspection (Alpaca)
- **Day 2 integration status: adapters implemented behind ECHO MarketDataProvider** (`backend/app/market/providers/alpaca.py`,
  secondary/fallback per D-009; `alpaca.data.models.Bar` never leaves that module). Day 9 execution is not part of Day 2.
- **Versions.** Installed `alpaca-py` 0.44.0 (backend lockfile; verified with `importlib.metadata`). Upstream inspected at
  `232179c` (2026-09-15); its `pyproject.toml` says `version = "0.0.0"`, so treat the installed 0.44.0 as authoritative.
- **Constructor** (`alpaca/data/live/stock.py`): `StockDataStream(api_key, secret_key, raw_data=False, feed=DataFeed.IEX,
  websocket_params=None, url_override=None, data_timeout=None)`. `subscribe_bars(handler, *symbols)` = minute bars; handler is
  `Callable[[Bar|Dict], Awaitable[None]]` and `_ensure_coroutine` (`websocket.py:511`) rejects non-coroutines.
- **Run model** (`alpaca/data/live/websocket.py`). `run()` (l.494) blocks: `asyncio.run(self._run_forever())`, `finally: self.stop()`.
  `stop()` (l.504) is thread-safe (`run_coroutine_threadsafe(stop_ws(), self._loop).result(timeout=5)`). The only awaitable is the
  private `_run_forever()` (l.421); there is no public async runner. The ECHO adapter therefore runs `run()` in a dedicated
  daemon thread and hands bars to the app loop via `call_soon_threadsafe` into a bounded queue; driving `_run_forever()` on
  our own loop would deadlock runtime (un)subscribe (their `.result()` waits on the same loop).
- **`DataFeed`** (`alpaca/data/enums.py:56`, `str` Enum): `IEX="iex"`, `SIP="sip"`, `DELAYED_SIP="delayed_sip"`, `OTC="otc"`,
  `BOATS="boats"`, `OVERNIGHT="overnight"`. Default IEX (free); SIP needs a paid subscription.
- **`Bar`** (`alpaca/data/models/bars.py`): `symbol, timestamp (datetime, bar OPEN time), open, high, low, close, volume,
  trade_count, vwap` (docstring also lists `exchange`, but it is not a declared field). No end timestamp: derive bar-end
  as start + interval in the adapter.
- **Reconnect.** `_reconnect_min_backoff=1.0`, `_reconnect_max_backoff=30.0` (`websocket.py:112-113`), `_wait_before_reconnect`;
  `data_timeout` must be `> 0` or `ValueError`, off by default.

---

# Tier 2 — Architecture reference only

## nautechsystems/nautilus_trader

| Field | Value |
|-------|-------|
| Upstream | https://github.com/nautechsystems/nautilus_trader |
| Role in ECHO | Design reference for adapter boundaries, message bus, deterministic clock, event replay. **Not a dependency.** |
| Integration status | Not integrated. Not installed. Nothing copied. |
| Milestone | none (ideas feed Day 1 contracts, Day 2 adapters, Day 9 replay/backtest) |
| License | **LGPL-3.0-only** (`LICENSE`, `python/pyproject.toml`) |
| Last inspected | `9006e1e` (2026-09-20), `version.json`: v2.0.0rc6 (Rust core with Python layer) |

**What we use:** concepts only, re-implemented in our own code and words.
**What we do not use:** the package, its engines, its data model, any source. LGPL obligations and a
large Rust-based runtime are not worth taking on for a hackathon with a 50-100 asset universe (D-026).

**Important paths:** `docs/concepts/adapters.md`, `docs/concepts/message_bus.md`, `docs/concepts/architecture.md`,
`docs/concepts/event_sourcing.md`, `docs/concepts/backtesting/`, `crates/common/src/clients/data.rs` (`DataClient` trait),
`crates/common/src/clients/execution.rs`, `crates/common/src/clock/` (`virtual.rs` = test/replay clock),
`crates/backtest/src/` (`data_iterator.rs`, `engine.rs`), `python/nautilus_trader/live/clients.py`,
`python/nautilus_trader/adapters/{binance,databento,interactive_brokers,sandbox}`, `ADAPTERS.md`.

### Findings (ideas to borrow)
- **Adapter boundary.** An adapter = `HttpClient` + `WebSocketClient` + `InstrumentProvider` + `DataClient`
  + `ExecutionClient`; it translates venue protocols into engine domain objects, and strategies never touch
  transports. This matches ECHO's rule: SDK object -> adapter -> domain object.
- **`DataClient` lifecycle** (Rust trait): `client_id`, `venue`, `start`, `stop`, `reset`, `dispose`,
  `is_connected`/`is_disconnected`, plus subscribe/request methods. Worth mirroring in `MarketDataProvider`:
  explicit start/stop/health state.
- **Message bus** is topic-based pub/sub with data, events and commands; live data uses `data.<kind>...`,
  replayed/requested data uses `data.pipeline.<kind>...` so replay never masquerades as live. Good pattern for
  ECHO's asyncio-queue/Redis-Streams event bus (D-025).
- **Clock abstraction.** A live clock and a virtual/test clock share an interface, so the same strategy code runs
  live or in replay. ECHO should inject a `Clock` into the pipeline from Day 1-2 to make replay (D-028, D-031) cheap.
- **Backtest = data iterator + simulated venue** driving the same engines as live.
- No Massive or Alpaca adapter exists in this repo (adapters include Binance, Databento, Interactive Brokers, sandbox, etc.).

### Day 2 inspection (Nautilus)
- **Day 2 integration status:** design reference only; not installed, no imports, nothing copied. ECHO's own
  `MarketDataProvider` seam (`backend/app/market/providers/base.py`: `connect()`/`disconnect()`, plus
  `failover.py`, `supervisor.py`, `backoff.py`, `replay.py`) is the equivalent boundary.
- Inspected `9006e1e` (2026-09-20), `.reference-repos/nautilus-trader` (v2.0.0rc6).
- **Rust contract.** `crates/common/src/clients/data.rs` defines `pub trait DataClient` (`client_id`, `venue`,
  `start`, `stop`, `reset`, `dispose`, connection-state queries, subscribe/request methods); execution twin is
  `crates/common/src/clients/execution.rs`.
- **Python layer.** `python/nautilus_trader/live/clients.py` has `DataClientFactory`, `DataClient(_Client)`
  (requires `DataClientConfig`) and `MarketDataClient(DataClient)`; live adapters live under
  `python/nautilus_trader/adapters/` (binance, databento, interactive_brokers, sandbox, ...). No Massive or Alpaca adapter.
- **Borrowed idea only:** explicit lifecycle + health state on the provider, SDK objects never crossing the adapter boundary.

## QuantConnect/Lean

| Field | Value |
|-------|-------|
| Upstream | https://github.com/QuantConnect/Lean |
| Role in ECHO | Design reference for replay/backtest structure and brokerage abstraction. **Not integrated.** |
| Integration status | Not integrated. Not installed. Nothing copied. |
| Milestone | none (ideas feed Day 9 backtest/replay) |
| License | **Apache-2.0** (`LICENSE`; Copyright 2014 QuantConnect Corporation) |
| Last inspected | `985ef30` (2026-09-18); C# (.NET) engine with Python algorithm bindings |

**What we use:** concepts only. **What we do not use:** the engine, Docker images, data formats, or any code
(C#/.NET stack; Conviction is the hackathon's strategy-validation tool, not Lean).

**Important paths:** `Common/Interfaces/` (`IBrokerage.cs`, `IDataQueueHandler.cs`, `IHistoryProvider.cs`,
`IDataProvider.cs`), `Engine/DataFeeds/` (`FileSystemDataFeed.cs` = backtest, `LiveTradingDataFeed.cs` = live,
`TimeSlice.cs`, `SubscriptionDataReader.cs`), `Engine/HistoricalData/`, `Engine/RealTime/`,
`Brokerages/Paper/`, `Algorithm.Framework/`.

### Findings (ideas to borrow)
- Live and backtest are two implementations of the same `IDataFeed`, with a common `TimeSlice` (all data at one
  timestamp), which keeps information boundaries explicit (D-028).
- `IDataQueueHandler.Subscribe(config, onNewData)` / `Unsubscribe` is the live-data provider seam; `IBrokerage` is the
  execution seam; a `Paper` brokerage exists for simulated fills. Analogues of ECHO's provider interfaces.
- `IHistoryProvider` separates history lookups from streaming; ECHO's REST backfill vs WS stream split mirrors this.

---

# Tier 3 — Future optional (not integrated)

Interactive Brokers access, only if IBKR execution is ever needed. Nothing in ECHO depends on these.

## ib-api-reloaded/ib_async

| Field | Value |
|-------|-------|
| Upstream | https://github.com/ib-api-reloaded/ib_async |
| Role in ECHO | Possible future IBKR data/execution provider (asyncio, wraps TWS/IB Gateway socket API) |
| Integration status | Not integrated |
| Milestone | none scheduled |
| License | **BSD-2-Clause** (`LICENSE`; `pyproject.toml` says `license = "BSD"`) |
| Last inspected | `ab629f3` (2025-12-06), version 2.1.0 |

**Important paths:** `ib_async/ib.py`, `ib_async/client.py`, `ib_async/wrapper.py`, `ib_async/contract.py`, `examples/`.
Requires a running TWS or IB Gateway. Would implement `MarketDataProvider`/`ExecutionProvider` behind the same adapter rule.

## Voyz/ibind

| Field | Value |
|-------|-------|
| Upstream | https://github.com/Voyz/ibind |
| Role in ECHO | Possible future IBKR access via the Client Portal Web API (REST + WebSocket, OAuth) |
| Integration status | Not integrated |
| Milestone | none scheduled |
| License | **Apache-2.0** (`LICENSE`; Copyright 2020 Voy Zan) |
| Last inspected | `99b459b` (2026-09-06), version 0.2.1 |

**Important paths:** `ibind/client/ibkr_client.py`, `ibind/ws/`, `ibind/oauth/`, `examples/`.
