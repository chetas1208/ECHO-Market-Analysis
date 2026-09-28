# Day 2 contract — module signatures (binding for all Day 2 agents)

Read first: `decisions.md`, `Plan.md` §8/11, `UI.md`, `docs/audits/parts/ENV.md`. Existing Day 1 code stays; extend, don't rewrite.
Already written (DO NOT edit unless you own it): `backend/app/market/types.py`, `settings.py`, `providers/base.py`, `backend/config/universe.yaml`.
Deps (installed by lead before you start): polars, pyyaml, numpy, massive, alpaca-py. Tests: `backend/tests/market/test_<module>.py`, pure unit tests, NO network, NO credentials. Style: ruff (line 100), typed, small.

Conventions
- Frames: one Polars DataFrame per symbol, ascending `timestamp` (`pl.Datetime("us","UTC")`), columns `open high low close volume` (Float64) + optional `vwap trade_count`. Always sort defensively; drop duplicate timestamps keeping last.
- Returns are LOG returns: `ln(close_t / close_{t-h})`, h in 1m bars (1/5/15).
- STRICT NO-LOOKAHEAD: every rolling baseline for row t uses rows `< t` only (shift(1) before rolling) or documents `<= t` for the value itself; baseline excludes current value. Feature at t never reads t+1.
- Zero variance / insufficient samples → `None` (never inf/NaN). Status READY only when ≥ `min_*` samples.
- UTC-aware datetimes everywhere. Config constants only via `MarketSettings` (`app.market.settings.get_market_settings()`), never magic numbers.

## Modules and signatures

`app/market/universe.py`
- `class UniverseEntry(BaseModel): symbol, group, role ("equity"|"benchmark"), sector_benchmark: str|None`
- `class Universe: entries; market_benchmark: str; symbols() -> list[str]; equities() -> list[str]; benchmarks() -> list[str]; sector_benchmark_for(symbol) -> str; group_of(symbol) -> str|None`
- `load_universe(path: Path = UNIVERSE_PATH) -> Universe` (validates: benchmarks referenced exist; no duplicate symbols); `get_universe()` cached.

`app/market/calendar.py` (NYSE, America/New_York, zoneinfo; embedded holidays 2025–2027 incl. half days 13:00 close)
- `class Session(StrEnum): CLOSED, PREMARKET, REGULAR, AFTERHOURS`
- `class MarketCalendar: session_at(ts) -> Session; is_regular(ts) -> bool; session_bounds(d: date) -> tuple[datetime, datetime] | None (UTC open, close; None on holiday/weekend); is_trading_day(d) -> bool; expected_active(ts) -> bool (regular session only); minutes_since_open(ts) -> int | None; next_open(ts) -> datetime`

`app/market/aggregation.py`
- `class BarAggregator(intervals=(M5, M15)): add(bar: Bar) -> list[Bar]` — feed closed 1m bars (any order tolerated only for exact duplicates → ignored); emits completed 5m/15m bars aligned to clock buckets (:00/:05…, :00/:15…) inside a session; a bucket completes when a bar of a later bucket arrives or the last 1m bar of the bucket arrives; partial buckets (missing minutes) still emit with `trade_count`/volume summed; open=first, high=max, low=min, close=last, volume=sum, vwap=volume-weighted; `source` preserved.
- `aggregate_frame(df: pl.DataFrame, interval: Interval) -> pl.DataFrame` — batch equivalent (same semantics, group_by_dynamic).

`app/market/features/returns.py`
- `add_log_return(df, horizon_bars: int, out: str) -> pl.DataFrame` (null for first h rows).
`app/market/features/zscore.py`
- `add_rolling_z(df, col: str, out: str, window: int, min_periods: int) -> pl.DataFrame` baseline = previous `window` values (excludes current); null if fewer than min_periods or std==0.
- (file `features/volume.py`, NOT zscore.py) `add_volume_z(df, out: str, *, bucket_minutes: int, tod_min_days: int, rolling_window: int, min_periods: int) -> pl.DataFrame` — adds `out` and `f"{out}_method"` ("tod" if ≥tod_min_days prior sessions have that time-of-day bucket, else "rolling", else null). Time-of-day bucket = minutes since midnight ET // bucket_minutes. Uses prior sessions only.
`app/market/features/volume.py` — see add_volume_z above.
`app/market/features/volatility.py`
- `add_realized_vol(df, window_bars: int, out: str)`: `sqrt(sum(r_1m^2))` over last window (incl. current bar's return); needs `ret_1m` column (add if missing).
- `add_vol_z(df, rv_col: str, out: str, window: int, min_periods: int)`.
`app/market/features/beta.py`
- `add_rolling_beta(df, stock_ret: str, bench_ret: str, out: str, window: int, min_periods: int)`: beta = cov/var over previous window (excludes current row); null on var==0.
- (file `features/residual.py`, NOT beta.py) `add_residual(df, stock_ret_h: str, bench_ret_h: str, beta_col: str, out: str)`: `stock_ret_h - beta*bench_ret_h`; cold-start: null (explicit, no beta=1 silent fallback).
`app/market/features/engine.py`
- `class FeatureEngine(universe: Universe, cfg: FeatureConfig): compute(symbol: str, frames: dict[str, pl.DataFrame]) -> SymbolFeatures` — frames keyed by symbol (must include stock, market benchmark, sector benchmark); uses only the last row's causal features. `return_z` = z of `ret_5m` (5-bar horizon return) against baseline of past `ret_5m` values; `volatility_z` = z of realized vol; residuals use 5-bar returns and beta from 1-bar returns; `*_residual_z` = residual vs rolling std of past residuals. Status per feature: READY / WARMING_UP (some but < min samples) / UNAVAILABLE (no data or benchmark missing). `overall_status` READY iff return_z, volume_z, volatility_z, market_residual_z, sector_residual_z all READY. Missing bar / gaps: features computed on available rows only, never forward-filled.

`app/market/shock/score.py`
- `component(z: float|None, cap: float) -> float` = `min(abs(z)/cap, 1)` (0 if None); volume uses `max(z,0)`.
- `assess(f: SymbolFeatures, cfg: ShockConfig) -> ShockAssessment`: score = Σ w_k·component_k over ret, volume, volatility, sector, market (weights from cfg, must sum≈1; normalise); `ready = f.overall_status == READY`; if not ready → level NONE, score kept but `ready=False`; level from thresholds (watch/shock/severe); direction from sign of `sector_residual` (fallback `market_residual`, fallback `ret_5m`), None if all null; `calibrated=False` always.
`app/market/shock/cooldown.py`
- `class ShockCooldown(cooldown_seconds): should_emit(symbol, direction, level, as_of) -> bool` — first shock emits; same (symbol,direction) within cooldown suppressed UNLESS level escalates (shock→severe); `reset()`; `snapshot() -> dict`.
`app/market/shock/events.py`
- `build_shock_event(assessment, features, provider: ProviderName) -> EventCreate` (from `app.schemas.event`): `source_type=market`, `event_type="market_shock"`, deterministic `id = f"evt_mkt_{symbol.lower()}_{as_of:%Y%m%d%H%M}_{direction[:3]}"` (dupes are harmless: creation is idempotent-by-id), `title` "NVDA abnormal downside move" / "upside", `companies=[symbol]`, `severity=score`, `novelty=1.0`, `confidence` = fraction of the 5 components ≥ 0.5 (signal agreement — NOT a probability), `economic_channels={}`, `timestamp=as_of`, `metadata` = {direction, level, shock_score, calibrated:false, return_5m, return_z, volume_z, volume_z_method, volatility_z, sector_residual, market_residual, sector_benchmark, provider, components}, `summary` short factual line, `source_refs=[{"name": provider}]`, `is_mock` = true iff provider == replay.
`app/market/shock/detector.py`
- `class MarketShockDetector(cfg: ShockConfig): evaluate(f: SymbolFeatures) -> ShockDecision`; `ShockDecision(emit: bool, assessment: ShockAssessment, reason: str)`. Only emits when ready, level ≥ SHOCK, cooldown allows, and `as_of` not already evaluated for that symbol (bar dedupe).

`app/market/providers/backoff.py`: `backoff_delays(cfg: ReconnectConfig, rng: random.Random|None=None) -> Iterator[float]` exponential + ± jitter, capped.
`app/market/providers/replay.py`: `ReplayMarketDataProvider(bars: Sequence[Bar], speed: float = 0.0, name=REPLAY)` implements MarketDataProvider; deterministic order (timestamp, symbol); `health()` mode=REPLAY; ends stream at end; supports `fail_after: int|None` for failure simulation (raises ConnectionError).
`app/market/fixtures.py`: `build_shock_scenario() -> ShockScenario(bars: list[Bar], shock_symbol: str, expected_shock_at: datetime, universe_symbols: list[str])`: deterministic (seeded), ≥ 420 normal 1m bars per symbol in one regular session preceded by ≥ 6 prior sessions of same time-of-day pattern only if cheap — otherwise document volume fallback; then a NVDA-only abnormal move (−4.5% over 5 bars, volume ×8, SOXX flat, SPY flat). Provide also `build_normal_scenario()` (no shock).
`app/market/providers/massive.py`: `normalize_massive_agg(msg, received_at) -> Bar | None` (pure; minute aggregates `AM`; Unix ms timestamps; malformed → None + counter); `MassiveMarketDataProvider(api_key, symbols)` using official `massive` WebSocketClient (`await client.connect(handler)`; pass api_key explicitly; asyncio; bounded internal queue). Unconfigured → state UNCONFIGURED, `connect()` raises `ProviderUnconfigured`.
`app/market/providers/alpaca.py`: `normalize_alpaca_bar(bar, received_at) -> Bar | None`; `AlpacaMarketDataProvider(api_key, api_secret, feed)` using `StockDataStream.subscribe_bars` (coroutine handlers).
`app/market/providers/supervisor.py`: `SupervisedProvider(factory: Callable[[], MarketDataProvider], reconnect: ReconnectConfig, clock=time.monotonic, sleep=asyncio.sleep, rng)`: states DISCONNECTED→CONNECTING→CONNECTED→(DEGRADED|RECONNECTING|STALE); on stream error → RECONNECTING with backoff; `touch()` on each message; stale detector (`check_stale(now, calendar.expected_active)`); `stream()` yields bars across reconnects; never raises to caller except on stop; `health()`.
`app/market/providers/failover.py`: `class FailoverSelector(primary: ProviderName, fallback: ProviderName|None): update(health_by_provider) -> ProviderName` active provider (primary while healthy = CONNECTED/DEGRADED-not-stale; else fallback if healthy); `class BarDeduper(max_keys=50_000): seen(bar) -> bool` by (symbol,timestamp,interval) across providers — authoritative provider wins.

`app/repositories/market.py` (`MarketBarRepository(session)`): `upsert_bars(bars: Sequence[Bar]) -> int` (INSERT … ON CONFLICT (symbol,timestamp,source,timeframe) DO UPDATE — bars for a closed bucket are idempotent; batch executemany); `get_bars(symbol, interval, start=None, end=None, limit=500) -> list[Bar]` ascending, limit ≤ 2000 hard cap; `load_recent(symbol, interval, n) -> list[Bar]` ascending; `latest_timestamp(symbol=None) -> datetime|None`.
Migration `0004_market_extras`: add `received_at timestamptz null` to market_observations; index `(symbol, timeframe, timestamp DESC)`; CHECK timeframe IN ('1m','5m','15m'); `ALTER TABLE forecast_runs/points ENABLE ALWAYS TRIGGER` for the 4 immutability triggers (superuser-bypass repair); update ORM model.

`app/market/pipeline.py`: `class MarketPipeline(provider, universe, settings, session_factory, event_sink)`:
- bounded `asyncio.Queue(maxsize=settings.echo_market_queue_size)`; overflow policy = drop OLDEST + increment `dropped` counter + WARN log (rate-limited).
- consumer loop: dedupe → aggregate (5m/15m) → keep per-symbol Polars history (cap `history_bars`) → batch upsert 1m/5m/15m bars → on each closed 1m bar of an EQUITY symbol compute features (only after its benchmark bars exist) → detector → if emit: `await event_sink(event)`.
- `latest_features: dict[str, SymbolFeatures]`, `latest_prices`, `status() -> PipelineStatus` (mode, provider healths, queue depth, dropped, subscribed symbols, last_observation_at, replay_finished).
- Provider errors never propagate out of `run()`.
`app/market/runtime.py`: `MarketRuntime(settings, session_factory)`: `start()` builds provider(s) per `echo_market_provider` (off → no task, mode OFFLINE; replay → ReplayMarketDataProvider(shock scenario); massive/alpaca → SupervisedProvider; unconfigured → state UNCONFIGURED, app still boots), starts pipeline as background task; `stop()` cancels cleanly. Wired into FastAPI lifespan (`app/main.py`), stored on `app.state.market_runtime`. Events created via existing `EventService.create` in its own session; duplicate id → treated as success.

`app/schemas/market.py` + `app/api/v1/market.py` (router included in `app/api/v1/router.py`, prefix `/market`). Errors use the existing envelope. All ts ISO-8601 Z.
- `GET /api/v1/market/status` → `{"mode":"LIVE|REPLAY|MOCK|OFFLINE","providers":[ProviderHealth…],"active_provider":str|null,"subscribed_symbols":[…],"last_observation_at":ts|null,"queue":{"depth":int,"capacity":int,"dropped":int},"replay_finished":bool,"session":"REGULAR|…"}`
- `GET /api/v1/market/symbols` → `{"items":[{"symbol","group","role","sector_benchmark","price":float|null,"change_pct":float|null,"as_of":ts|null,"state":"NORMAL|WATCH|SHOCK|SEVERE|WARMING_UP|NO_DATA","shock_score":float|null,"volume_z":float|null,"return_5m":float|null,"sector_residual":float|null,"direction":"positive|negative"|null}]}`
- `GET /api/v1/market/bars/{symbol}?interval=1m|5m|15m&start=&end=&limit=` (limit 1..2000, default 300) → `{"symbol","interval","items":[{"timestamp","open","high","low","close","volume","source"}]}`; unknown symbol 404; bad interval 422.
- `GET /api/v1/market/features/{symbol}` → SymbolFeatures JSON (+ `assessment`: ShockAssessment|null); 404 unknown symbol.
- `GET /api/v1/market/shocks?limit=50` → `{"items":[Event…]}` = canonical events where `source_type='market' AND event_type='market_shock'` newest first (same Event JSON as /events).
Canonical events endpoint `/events` also gains optional `source_type` and `event_type` query filters.

## Frontend (UI.md rules apply: ≤5 tabs, overlay drawer w/ dim+blur, no page shift)
Types in `frontend/types/market.ts` mirror the JSON above. Client fns in `frontend/lib/api.ts` (or `lib/marketApi.ts`): `getMarketStatus, getMarketSymbols, getBars, getFeatures, getShocks`. Polling hook (5 s default, pauses when tab hidden). Components under `frontend/components/market/`: `ModeBadge` (LIVE / REPLAY / MOCK / OFFLINE — visually unmistakable, in the header), `FeedStatus` (per-provider state, last message, subscribed count), `SymbolTable` (dense: price, %chg, volume z, state), `ShockCard`/shock rows (score shown as "Shock score 0.86", never a percent-confidence), `PriceChart` (inline SVG, no chart lib: close line + shock marker + interval selector). Event list shows a MARKET SHOCK badge for `source_type=market`. Integrate into existing routes per UI.md (Dashboard / Events); do NOT add a 6th nav tab.

## Testing rules
Each module has tests in `backend/tests/market/` (or `frontend/components/__tests__`). Cover: normal, insufficient history, zero variance, duplicates, extremes, no-lookahead (append future rows → earlier features unchanged). DB tests use the existing `echo_test` fixtures (see `backend/tests/conftest.py`). Do not modify files you don't own; if you need a change elsewhere, say so in your report.
