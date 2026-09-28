# ECHO market data (Day 2)

Source of truth is the code in `backend/app/market/`; every number below was read from it. Shock output is a **heuristic anomaly score, not a calibrated probability** (`calibrated: false` everywhere).

## 1. Architecture

```text
 Massive WS (AM.<SYM>) --+
 Alpaca WS  (1m bars)  --+--> SupervisedProvider --> normalized Bar (closed 1m, UTC)
 Replay (fixtures)  -----+    (backoff, stale)                |
                                                              v
                     pipeline queue (5000; live: drop-oldest, replay: blocks)
                                                              |
        BarDeduper: only the ACTIVE provider's bars, first (symbol,ts,interval) wins
                                                              |
                +---------------------+-----------------------+
                v                     v                       v
       in-memory 1m history    BarAggregator 5m/15m     batched upsert
       (2730 bars/symbol)      (UTC-aligned buckets)    market_observations
                |                                       (1m + 5m + 15m)
                v  on each closed 1m EQUITY bar, once SPY + sector-ETF bars of that minute exist
       FeatureEngine (Polars/NumPy, causal) -> SymbolFeatures
                v
       MarketShockDetector: score -> ready gate -> level -> bar dedupe -> cooldown
                v
       canonical event (market_shock)  --> events table (deterministic id, idempotent)
                v
       REST /api/v1/market/*  <---- UI polls every 5 s (bars every 10 s), badge = data mode
```

Ownership: `types.py` (Bar, states), `settings.py` (all defaults), `universe.py` + `config/universe.yaml`, `calendar.py`, `aggregation.py`, `providers/*`, `features/*`, `shock/*`, `pipeline.py`, `runtime.py`, `repositories/market.py`, `api/v1/market.py`.

## 2. Providers

| Provider | Role | Select with | Notes |
|---|---|---|---|
| Massive | primary live | `ECHO_MARKET_PROVIDER=massive`, `MASSIVE_API_KEY` | Websocket minute aggregates `AM.<SYM>`; SDK retries internally (`max_reconnects=3`) then surfaces `ConnectionError` to the supervisor. `trade_count` is always `None` (wire `z` is average trade size, not a count). |
| Alpaca | fallback / secondary | `ECHO_MARKET_FALLBACK=alpaca` (or `ECHO_MARKET_PROVIDER=alpaca`), `ALPACA_API_KEY`, `ALPACA_API_SECRET`, `ALPACA_FEED=iex\|sip` (default `iex`) | Runs the alpaca-py stream in a daemon thread. **IEX** (free) is one exchange only: volume is a fraction of consolidated volume and quiet symbols can have missing minutes. **SIP** is the consolidated feed and needs a paid Alpaca data subscription. |
| Replay | tests / dev only | `ECHO_MARKET_PROVIDER=replay` | Deterministic, no network, `received_at` = bar timestamp. Always `mode=REPLAY`; events it produces have `is_mock=true`. It can never be reported as `LIVE` (enforced in the pipeline and again in `api/v1/market.py::_reported_mode`). |

Selection rules (`runtime.py`, `providers/failover.py`, `pipeline.py`):

- **Priority**: `ECHO_MARKET_PROVIDER` is the primary. `ECHO_MARKET_FALLBACK=alpaca` adds Alpaca as fallback only when the primary is `massive`. If the primary has no credentials but the fallback does, the fallback is promoted to primary. No usable provider = runtime stays `OFFLINE`, API still boots.
- **Both streams run concurrently** (one producer task each). Only the *active* provider's bars are accepted; the other's are dropped (`BarDeduper.dropped_non_active`).
- **Failover** (`FailoverSelector`, evaluated by a monitor every 1 s): healthy means `CONNECTED` only (`DEGRADED`, `STALE`, `RECONNECTING`, ... are unhealthy). Primary unhealthy and fallback `CONNECTED` = switch immediately. Switch back needs the primary `CONNECTED` for 3 consecutive polls (hysteresis, about 3 s). There is no historical backfill across a switch.
- **Dedupe layers**: (1) `BarDeduper` LRU 50,000 keys, first `(symbol, timestamp, interval)` wins; (2) `BarAggregator` drops a repeated 1m timestamp per symbol, first wins; (3) DB unique key `(symbol, timestamp, source, timeframe)` with upsert (last write wins); (4) API returns one bar per timestamp, preferring the active provider, else alphabetical source; (5) detector requires strictly increasing `as_of` per symbol. Because of (1), a provider "correction" of an already-seen bar is ignored.
- `MOCK` exists in `DataMode` and the UI badge, but no provider currently emits it.

## 3. Normalized `Bar` (`types.py`)

Provider SDK objects never leave the adapters. Timestamps are timezone-aware UTC; `timestamp` is the bar **start**. Providers emit only closed 1m bars; 5m/15m are built locally.

| Field | Type | Rule |
|---|---|---|
| `symbol` | str | upper-cased, non-empty |
| `timestamp` | datetime (UTC) | bar start, must be tz-aware |
| `interval` | `1m` \| `5m` \| `15m` | default `1m` |
| `open/high/low/close` | float | all > 0; `high >= max(o,c,l)`, `low <= min(o,c,h)` else rejected |
| `volume` | float | >= 0 |
| `vwap` | float \| None | Massive `vw`; Alpaca `vw`; ignored if <= 0 |
| `trade_count` | int \| None | Alpaca `n`; Massive always None |
| `source` | `massive` \| `alpaca` \| `replay` | |
| `received_at` | datetime \| None | provider wall clock at receipt (replay: bar ts) |

Malformed messages become `None` and increment `malformed_messages`; they never raise. Aggregation (`aggregation.py`): buckets align to the UTC clock (`minute % interval`), `open=first, high=max, low=min, close=last, volume=sum`, vwap volume-weighted over bars that carry one, `trade_count=sum` (None if none). Emitted when the bucket's last minute arrives, or when a later bucket starts; partial buckets flush at end of stream. Aggregates are persisted and served by the API; features use the 1m series only.

## 4. Universe and sector benchmarks (`config/universe.yaml`)

35 symbols: 29 equities + 6 benchmarks. Market benchmark **SPY**. `default_sector_benchmark: SPY` applies only to symbols with no `sector_benchmark` (every current equity has one).

| Sector ETF | Equities |
|---|---|
| SOXX | NVDA AMD AVGO TSM INTC QCOM MU |
| QQQ | MSFT AMZN GOOGL META AAPL CRWD PANW |
| XLE | XOM CVX COP SLB LNG |
| XLI | DAL UAL AAL LUV LMT RTX NOC |
| XLF | JPM BAC GS |

Benchmarks: SPY, QQQ, SOXX, XLE, XLF, XLI. Airlines and defense map to XLI only because there is no dedicated liquid ETF in the set; cybersecurity maps to QQQ. **This mapping is a return co-movement baseline for residuals. It is not an economic-exposure claim** (the event's `economic_channels` is `{}`). Benchmarks are ingested, persisted and priced but never evaluated (no features/shock for them). The YAML is validated at load (duplicate symbols, benchmark existence).

## 5. Features (`features/*.py`, `SymbolFeatures`)

All baselines for row *t* use rows strictly before *t*; nothing after *t* is read; frames handed to the engine are truncated to the evaluated bar. Series are never forward filled: "N bars" means N *available* rows, so a missing minute stretches the lookback. z-scores use sample std (ddof=1) and are `null` on zero variance, never inf/NaN. Defaults (`FeatureConfig`): `baseline_bars=390`, `min_baseline_bars=60`, `beta_window_bars=390`, `min_beta_bars=60`, `vol_window_bars=15`, `tod_bucket_minutes=5`, `tod_min_days=5`, `history_bars=2730` (7 sessions x 390, in memory per symbol).

| Feature | Definition |
|---|---|
| `ret_1m/5m/15m` | `ln(close_t / close_{t-h})`, h = 1, 5, 15 rows. Log returns. |
| `return_z` | z of `ret_5m` vs the previous 390 non-null `ret_5m` values (min 60). |
| `volume_z` | see below. `volume_z_method` = `"tod"` or `"rolling"`. |
| `rv` (internal) | `sqrt(sum(r_1m^2))` over the last 15 1m log returns, current included. Not annualized. Not in the API. |
| `volatility_z` | z of `rv` vs the previous 390 `rv` values (min 60). |
| `beta_market`, `beta_sector` | `cov(r_1m, bench_r_1m) / var(bench_r_1m)` over the previous 390 rows, at least 60 valid pairs, zero benchmark variance = null. |
| `market_residual`, `sector_residual` | `ret_5m - beta * bench_ret_5m`. Beta is estimated on 1m returns and applied to 5m returns. **No `beta = 1` fallback**: missing beta = null residual. |
| `market_residual_z`, `sector_residual_z` | z of the residual vs the previous 390 residuals (min 60). |

**Volume z (time-of-day).** Intraday volume is U-shaped, so each bar is compared with the *same 5-minute ET wall-clock bucket* (`minutes_since_midnight_ET // 5`, DST-stable) on earlier sessions. Method `tod` is used when at least `tod_min_days=5` strictly earlier ET sessions have observations in that bucket: `z = (v - mean) / std` over all prior-session observations in the bucket (the current session is never in its own baseline). Otherwise method `rolling` (fallback): the previous 390 bars, min 60. **Seasonality limitation:** the rolling fallback ignores time of day, so during warm-up the open/close volume surge is compared with quiet bars and looks anomalous. Evidence from the replay scenario: with warm-up sessions evaluated, an unmodified NVDA session open scored `volume_z=5.75` (`rolling`), score 0.56 = SHOCK-level event with no injected anomaly. Treat `rolling` z as lower quality; the API and event metadata expose the method.

**Status per feature:** `READY` value non-null; `WARMING_UP` stock frame exists but value null (too little history, or zero variance); `UNAVAILABLE` no stock frame, or required benchmark frame missing / has no bar at `as_of` / symbol *is* the benchmark. `overall_status` = `READY` only if `return_z`, `volume_z`, `volatility_z`, `market_residual_z` and `sector_residual_z` are all `READY`; else `UNAVAILABLE` if any is `UNAVAILABLE`, else `WARMING_UP`. With continuous 1m data the first `READY` is row index 121 (the 122nd bar, about two regular-session hours): `ret_5m` from row 5, `volume_z` (rolling) 60, `beta` 61, `return_z` 65, `volatility_z` 75, residual z 121 (measured on the replay scenario). `tod` volume first appears on session 6.

**No-lookahead guarantee.** Each baseline shifts by one row (`shift(1)` / `[i-window, i)` windows) and evaluation happens only on closed bars; the pipeline holds an equity bar until the SPY and sector-ETF bars of the same minute exist (max wait 10 s wall clock, or as soon as a later minute is seen), then computes on frames cut at that bar. `as_of` is the start timestamp of the last closed 1m bar used.

## 6. Shock score (`shock/`)

```
component_k = min(|z_k| / z_cap, 1)        z_cap = 6.0     (volume: max(z, 0) first; None -> 0)
score       = sum_k w_k * component_k                       (clamped to [0,1])
```

| k | z used | weight |
|---|---|---|
| ret | `return_z` | 0.30 |
| volume | `volume_z` (positive side only) | 0.20 |
| volatility | `volatility_z` | 0.20 |
| sector | `sector_residual_z` | 0.20 |
| market | `market_residual_z` | 0.10 |

Weights must be non-negative and sum to 1 (validated, and renormalized defensively). Levels: `none < 0.35 <= watch < 0.55 <= shock < 0.75 <= severe`. Levels are `none` unless `overall_status == READY`. Only `shock` and `severe` can emit an event; `watch` is shown in the UI state only.

- **Direction** (sign only, not part of the score): first non-null, non-zero of `sector_residual`, `market_residual`, `ret_5m` decides `positive`/`negative`. No value = no direction = no event. The score uses `|z|`, so it is symmetric; direction can differ from the sign of the raw `ret_5m` when the residual disagrees.
- **Cooldown**: per `(symbol, direction)`, 900 s (`cooldown_seconds`). A repeat is suppressed unless the level escalates (`shock` -> `severe`) or 900 s have passed. Time is taken only from `as_of`, so replays are deterministic. Out-of-order `as_of` never emits.
- **Bar dedupe**: the detector ignores a symbol's `as_of <= last evaluated as_of` (`duplicate_bar`). Decision reasons: `not_ready`, `below_threshold`, `no_direction`, `cooldown`, `duplicate_bar`, `emit`.
- **Volume is not a hard gate.** Volume is one 20 % component; a shock can fire with zero volume contribution (e.g. all four other z at 6 = 0.80 = `severe`).
- **Heuristic, not a probability.** Weights and thresholds are an unoptimized starting point (D-023). The score is not calibrated against outcomes and must not be read as P(event). The five inputs are also strongly correlated (all derive from the same price path), so they are not independent evidence.
- **Event `confidence` = signal agreement, not probability**: the fraction of the five components that are >= 0.5 (values 0, 0.2, ..., 1.0). Metadata carries `confidence_semantics: "signal_agreement_not_probability"` and `calibrated: false`. Worked example: z = (ret -4, volume 6, vol 3, sector -4, market -3) gives components (0.667, 1, 0.5, 0.667, 0.5), score 0.683 (`shock`, negative), confidence 1.0.

Canonical event (`shock/events.py`): `id = evt_mkt_<sym>_<YYYYMMDDHHMM>_<pos|neg>` (deterministic, so re-emission is idempotent; a duplicate id counts as success), `source_type=market`, `event_type=market_shock`, `severity=score`, `novelty=1.0`, `companies=[symbol]`, `economic_channels={}`, `source_refs=[{name: provider}]`, `is_mock = (provider == replay)`. Failed sink writes are retried (up to 100 kept in memory).

## 7. Market calendar (`calendar.py`)

NYSE, `America/New_York` via `zoneinfo` (DST-safe). Sessions (ET): `PREMARKET` 04:00-09:30, `REGULAR` 09:30-16:00 (13:00 on early-close days), `AFTERHOURS` until 20:00, else `CLOSED`; weekends and full holidays are `CLOSED`. Holidays and early closes are embedded for **2025-2027 only** (weekend holidays shifted to Fri/Mon; 13:00 closes: 2025-07-03, 2025-11-28, 2025-12-24, 2026-11-27, 2026-12-24, 2027-11-26). Outside those years every weekday is a plain regular day (`covers_year()` reports coverage).

The calendar is used for: (a) staleness gating (`expected_active` = regular session only) and (b) the `session` field of `/status` (wall clock, upper-case). It does **not** filter bars: the pipeline ingests, persists and evaluates whatever the provider sends, including extended-hours bars.

## 8. Reconnect, backoff, stale, provider states

`ProviderState`: `UNCONFIGURED`, `DISCONNECTED`, `CONNECTING`, `CONNECTED`, `DEGRADED`, `RECONNECTING`, `STALE`.

- `SupervisedProvider` wraps Massive/Alpaca (not Replay). Flow: `DISCONNECTED -> CONNECTING -> CONNECTED -> (RECONNECTING | STALE)`. Failures never escape; each failure increments `reconnect_attempts` and sleeps `min(60, 1.0 * 2^n) * (1 + U(-0.3, +0.3))` seconds (`ReconnectConfig`: base 1 s, max 60 s, factor 2, jitter 0.3). The delay sequence restarts after the first received bar. On reconnect the adapter is rebuilt and symbols resubscribed.
- **UNCONFIGURED** (no key): no retries, API boots, `/status` shows the provider with `last_error: "credentials not configured"`.
- **STALE**: state is `CONNECTED`/`DEGRADED`, the calendar says `REGULAR`, and no bar for `stale_after_s = 90`. STALE clears on the next bar or when the market is not in regular session (so nights and weekends do not raise STALE, and STALE does not trigger failover then). STALE is evaluated when health is polled.
- **DEGRADED**: inner provider reports it (Alpaca stream thread died), or a bare (unsupervised) provider raised in connect/subscribe/stream (pipeline records the error and continues).
- **Data mode** (`/status.mode`): `REPLAY` for replay; `LIVE` only when the active live provider is `CONNECTED`; otherwise `OFFLINE`. So a live provider that is `STALE` or `RECONNECTING` shows `OFFLINE`, not `LIVE`.
- Queues drop the **oldest** bar when full (pipeline and Massive queues use `ECHO_MARKET_QUEUE_SIZE`, default 5000; the Alpaca adapter queue is fixed at 5000); `queue.dropped` in `/status` counts pipeline drops only. Replay blocks instead of dropping. A failing database keeps up to 50,000 unwritten bars and retries; features are unaffected. Persistence batches at 500 bars or 2 s.

## 9. Running it

```bash
# Docker in this sandbox may need the private daemon (Makefile note):
export DOCKER_HOST=unix:///tmp/echo-dockerd/docker.sock    # db on 127.0.0.1:5433
cp .env.example .env                                       # make env does this

# Replay: no keys. db-up + migrate + seed, then API :8100 and web :3000
ECHO_MARKET_PROVIDER=replay make dev-replay
# API only:  ECHO_MARKET_PROVIDER=replay make api
```

Replay = 4 symbols (NVDA, AMD, SOXX, SPY), 6 prior sessions (2026-09-08..15) + 1 shock day (2026-09-16), 10,920 bars; NVDA -4.5 % over 5 minutes at 16:00Z with 8x volume. Only the last session is evaluated; earlier sessions seed baselines. At `ECHO_MARKET_REPLAY_SPEED=0` (default) it takes about 1.5 minutes here (feature evaluation dominates); poll `replay_finished`. With speed > 0 it sleeps `gap_seconds / speed` between bars (speed 1.0 = real time = days of wall clock).

```bash
# Massive primary (+ optional Alpaca fallback). Put keys in .env, never commit them.
MASSIVE_API_KEY=... ECHO_MARKET_PROVIDER=massive ECHO_MARKET_FALLBACK=alpaca \
ALPACA_API_KEY=... ALPACA_API_SECRET=... ALPACA_FEED=iex  make api
# Alpaca only:  ECHO_MARKET_PROVIDER=alpaca ALPACA_API_KEY=... ALPACA_API_SECRET=... make api
```

Invalid market settings fall back to feed `off`; nothing here can block API startup. Feature/shock/reconnect defaults live in `settings.py` (code, not env vars).

Inspect (all on `:8100`; bars and shocks need the DB):

```bash
B=http://localhost:8100/api/v1/market
curl -s $B/status  | jq '{mode,active_provider,session,replay_finished,queue,providers:[.providers[]|{provider,state,last_error,reconnect_attempts}]}'
curl -s $B/symbols | jq '.items[]|select(.state!="NORMAL")'
curl -s "$B/bars/NVDA?interval=1m&limit=5"     # interval 1m|5m|15m, limit 1..2000 (default 300), start/end tz-aware
curl -s $B/features/NVDA | jq '{overall_status,volume_z_method,assessment}'
curl -s "$B/shocks?limit=5"                     # limit 1..200 (default 50), newest first
```

Unknown symbol = 404 error envelope; naive `start`/`end` or `start > end` = 422. Example responses (values rounded; produced by running the replay scenario through the runtime and the response models).

`GET /status`
```json
{
  "mode": "REPLAY",
  "providers": [{"provider": "replay", "state": "CONNECTED", "configured": true, "mode": "REPLAY",
    "last_message_at": "2026-09-16T19:59:00Z", "last_error": null, "reconnect_attempts": 0,
    "subscribed_symbols": ["AAL", "AAPL", "AMD", "..."], "messages_received": 10920, "malformed_messages": 0}],
  "active_provider": "replay",
  "subscribed_symbols": ["AAL", "AAPL", "AMD", "..."],
  "last_observation_at": "2026-09-16T19:59:00Z",
  "queue": {"depth": 0, "capacity": 5000, "dropped": 0},
  "replay_finished": true,
  "session": "CLOSED"
}
```

`GET /symbols` (one item; `change_pct` is percent vs the first observed 1m close of the latest ET session, not vs previous close; `state` is `NORMAL|WATCH|SHOCK|SEVERE|WARMING_UP|NO_DATA`; benchmarks carry price only)
```json
{"symbol": "NVDA", "group": "semiconductors", "role": "equity", "sector_benchmark": "SOXX",
 "price": 167.48, "change_pct": -5.59, "as_of": "2026-09-16T19:59:00Z", "state": "NORMAL",
 "shock_score": 0.0353, "volume_z": 0.179, "return_5m": -0.00125, "sector_residual": -0.00197,
 "direction": "negative"}
```

`GET /bars/NVDA?interval=1m&limit=2&end=2026-09-16T16:01:00Z` (no `vwap`/`trade_count` in the API)
```json
{"symbol": "NVDA", "interval": "1m", "items": [
  {"timestamp": "2026-09-16T16:00:00Z", "open": 178.94, "high": 179.20, "low": 176.63, "close": 177.34, "volume": 418297.0, "source": "replay"},
  {"timestamp": "2026-09-16T16:01:00Z", "open": 177.34, "high": 177.79, "low": 175.23, "close": 175.68, "volume": 338690.0, "source": "replay"}]}
```

`GET /features/NVDA` (final bar of the replay; `SymbolFeatures` + `assessment`; before any computation: `as_of: null`, `overall_status: "UNAVAILABLE"`)
```json
{"symbol": "NVDA", "as_of": "2026-09-16T19:59:00Z", "price": 167.48,
 "ret_1m": {"value": 0.000616, "status": "READY"}, "ret_5m": {"value": -0.00125, "status": "READY"},
 "ret_15m": {"value": 0.000942, "status": "READY"},
 "return_z": {"value": -0.117, "status": "READY"},
 "volume_z": {"value": 0.179, "status": "READY"}, "volume_z_method": "tod",
 "volatility_z": {"value": -0.420, "status": "READY"},
 "beta_market": {"value": 0.879, "status": "READY"}, "beta_sector": {"value": 0.781, "status": "READY"},
 "market_residual": {"value": -0.000911, "status": "READY"}, "market_residual_z": {"value": -0.0356, "status": "READY"},
 "sector_residual": {"value": -0.00197, "status": "READY"}, "sector_residual_z": {"value": -0.268, "status": "READY"},
 "sector_benchmark": "SOXX", "market_benchmark": "SPY", "overall_status": "READY",
 "assessment": {"symbol": "NVDA", "as_of": "2026-09-16T19:59:00Z", "score": 0.0353, "level": "none",
   "direction": "negative", "ready": true, "calibrated": false,
   "components": {"ret": 0.0195, "volume": 0.0299, "volatility": 0.0700, "sector": 0.0446, "market": 0.0059}}}
```

`GET /shocks` (`{"items": [Event]}`; the event the replay emits, as produced by the pipeline; the API adds `created_at`/`ingested_at`)
```json
{"id": "evt_mkt_nvda_202609161600_neg", "timestamp": "2026-09-16T16:00:00Z", "source_type": "market",
 "event_type": "market_shock", "title": "NVDA abnormal downside move",
 "summary": "NVDA severe downside move at 2026-09-16 16:00 UTC. Shock score 0.99 (heuristic, uncalibrated). 5m log return -0.0103, return z -5.87 sigma, volume z 18.73 sigma, volatility z 13.87 sigma, sector residual z -8.97 sigma, market residual z -7.73 sigma. Source: REPLAY (not live data).",
 "companies": ["NVDA"], "economic_channels": {}, "severity": 0.993, "novelty": 1.0, "corroboration": 0.0,
 "confidence": 1.0, "source_refs": [{"name": "replay"}], "is_mock": true,
 "metadata": {"direction": "negative", "level": "severe", "shock_score": 0.993, "calibrated": false,
   "confidence_semantics": "signal_agreement_not_probability", "return_5m": -0.01027, "return_z": -5.87,
   "volume_z": 18.73, "volume_z_method": "tod", "volatility_z": 13.87, "sector_residual": -0.01173,
   "market_residual": -0.01149, "sector_benchmark": "SOXX", "provider": "replay",
   "components": {"ret": 0.978, "volume": 1.0, "volatility": 1.0, "sector": 1.0, "market": 1.0}}}
```
The event fires at 16:00Z, the first shocked bar, earlier than the scenario's `expected_shock_at` (16:04Z, fifth shocked bar), because the first bar alone already saturates most components.

## 10. Limitations

- Shock weights (0.30/0.20/0.20/0.20/0.10), `z_cap=6`, thresholds and the 900 s cooldown are hand-chosen, not optimized or backtested; the score is uncalibrated.
- `tod` volume needs at least 5 prior sessions *of data this process has seen*. History is in memory only (2730 bars/symbol) and is **not** rehydrated from the DB or a REST backfill, so every restart is cold: `rolling` volume (with its open/close bias) until 5 sessions accumulate, and `READY` only after about 122 continuous 1m bars.
- Alpaca IEX volume is partial (single exchange) and bars can be missing for quiet symbols; after a Massive-to-Alpaca failover the volume scale changes inside one shared history, so `volume_z` can jump around the switch.
- Returns are over *available rows*, not clock time, and are not session-aware: a gap (missing minutes, overnight, holiday) is absorbed into one return, so the first bars of a session can carry the overnight gap. Extended-hours bars are processed if the provider sends them.
- `return_z`, `volatility_z` and residual z use overlapping windows (5-bar returns, 15-bar realized vol), so consecutive values are autocorrelated. Beta is a 1m-return estimate (noisy, ignores non-synchronous trading) applied to 5m returns.
- Massive `trade_count` is `None`; there are no quotes, bid/ask spread or order-book features yet.
- Sector ETFs are a co-movement baseline (airlines/defense to XLI, cybersecurity to QQQ), not an economic-exposure model.
- Calendar covers 2025-2027 only; outside that, weekdays are treated as regular days.
- Data mode and staleness use wall-clock time; `/status.session` therefore reflects "now", not the replay clock.
- Duplicate/corrected bars from a provider are ignored after the first copy; there is no correction handling.
- `MOCK` mode is defined but not produced by any provider; the UI only distinguishes what the runtime reports.
