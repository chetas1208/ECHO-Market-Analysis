import type { EchoEvent } from "./event";

/**
 * Day 2 market-data API types. Mirror `docs/day2-contract.md` (API section) and
 * `backend/app/market/types.py`. All timestamps are ISO-8601 UTC strings ("...Z").
 * Shock score is a heuristic, NOT a calibrated probability.
 */

/** What the UI must show. Replay/mock must never masquerade as LIVE. */
export type DataMode = "LIVE" | "REPLAY" | "MOCK" | "OFFLINE";

export type ProviderName = "massive" | "alpaca" | "replay";

export type ProviderState =
  | "UNCONFIGURED"
  | "DISCONNECTED"
  | "CONNECTING"
  | "CONNECTED"
  | "DEGRADED"
  | "RECONNECTING"
  | "STALE";

export type MarketSession = "CLOSED" | "PREMARKET" | "REGULAR" | "AFTERHOURS";

export type Interval = "1m" | "5m" | "15m";

export type FeatureStatus = "READY" | "WARMING_UP" | "UNAVAILABLE";

export type ShockDirection = "positive" | "negative";

export type ShockLevel = "none" | "watch" | "shock" | "severe";

export type SymbolRole = "equity" | "benchmark";

/** Per-symbol UI state derived by the backend. */
export type SymbolState =
  | "NORMAL"
  | "WATCH"
  | "SHOCK"
  | "SEVERE"
  | "WARMING_UP"
  | "NO_DATA";

export interface ProviderHealth {
  provider: ProviderName;
  state: ProviderState;
  configured: boolean;
  mode: DataMode;
  last_message_at: string | null;
  last_error: string | null;
  reconnect_attempts: number;
  subscribed_symbols: string[];
  messages_received: number;
  malformed_messages: number;
}

export interface MarketQueueStatus {
  depth: number;
  capacity: number;
  dropped: number;
}

/** GET /api/v1/market/status */
export interface MarketStatus {
  mode: DataMode;
  providers: ProviderHealth[];
  active_provider: ProviderName | null;
  subscribed_symbols: string[];
  last_observation_at: string | null;
  queue: MarketQueueStatus;
  replay_finished: boolean;
  session: MarketSession;
}

export interface MarketSymbolRow {
  symbol: string;
  group: string;
  role: SymbolRole;
  sector_benchmark: string | null;
  price: number | null;
  change_pct: number | null;
  as_of: string | null;
  state: SymbolState;
  shock_score: number | null;
  volume_z: number | null;
  return_5m: number | null;
  sector_residual: number | null;
  direction: ShockDirection | null;
}

/** GET /api/v1/market/symbols */
export interface MarketSymbolsResponse {
  items: MarketSymbolRow[];
}

/** One OHLCV bar as served by /market/bars (timestamp = bar start). */
export interface Bar {
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  source: ProviderName;
}

/** GET /api/v1/market/bars/{symbol}?interval=&start=&end=&limit= (limit 1..2000, default 300) */
export interface BarsResponse {
  symbol: string;
  interval: Interval;
  items: Bar[];
}

export interface FeatureValue {
  value: number | null;
  status: FeatureStatus;
}

export type VolumeZMethod = "tod" | "rolling";

/** Feature snapshot as of a closed 1m bar (no lookahead). Returns are log returns. */
export interface SymbolFeatures {
  symbol: string;
  as_of: string;
  price: number | null;
  ret_1m: FeatureValue;
  ret_5m: FeatureValue;
  ret_15m: FeatureValue;
  return_z: FeatureValue;
  volume_z: FeatureValue;
  volume_z_method: VolumeZMethod | null;
  volatility_z: FeatureValue;
  beta_market: FeatureValue;
  beta_sector: FeatureValue;
  market_residual: FeatureValue;
  market_residual_z: FeatureValue;
  sector_residual: FeatureValue;
  sector_residual_z: FeatureValue;
  sector_benchmark: string | null;
  market_benchmark: string | null;
  overall_status: FeatureStatus;
}

/** Heuristic score in [0, 1]. Never a calibrated probability (`calibrated` is always false). */
export interface ShockAssessment {
  symbol: string;
  as_of: string;
  score: number;
  level: ShockLevel;
  direction: ShockDirection | null;
  /** Contribution per signal (ret, volume, volatility, sector, market), each in [0, 1]. */
  components: Record<string, number>;
  ready: boolean;
  calibrated: boolean;
}

/** GET /api/v1/market/features/{symbol} = SymbolFeatures + assessment. */
export interface FeaturesResponse extends SymbolFeatures {
  assessment: ShockAssessment | null;
}

/** GET /api/v1/market/shocks?limit=50 — canonical market_shock events, newest first. */
export interface ShocksResponse {
  items: EchoEvent[];
}

export const INTERVALS: readonly Interval[] = ["1m", "5m", "15m"] as const;
export const DEFAULT_INTERVAL: Interval = "5m";

export const MODE_LABEL: Record<DataMode, string> = {
  LIVE: "LIVE",
  REPLAY: "REPLAY",
  MOCK: "MOCK",
  OFFLINE: "OFFLINE",
};

export const MODE_DESCRIPTION: Record<DataMode, string> = {
  LIVE: "Real-time provider data",
  REPLAY: "Replayed historical/synthetic bars - not live",
  MOCK: "Mock data - not live",
  OFFLINE: "No market data feed",
};

export const PROVIDER_STATE_LABEL: Record<ProviderState, string> = {
  UNCONFIGURED: "Unconfigured",
  DISCONNECTED: "Disconnected",
  CONNECTING: "Connecting",
  CONNECTED: "Connected",
  DEGRADED: "Degraded",
  RECONNECTING: "Reconnecting",
  STALE: "Stale",
};

export const SYMBOL_STATE_LABEL: Record<SymbolState, string> = {
  NORMAL: "Normal",
  WATCH: "Watch",
  SHOCK: "Shock",
  SEVERE: "Severe",
  WARMING_UP: "Warming up",
  NO_DATA: "No data",
};

/** True only for real provider data. Replay/mock/offline are never LIVE. */
export function isLiveMode(mode: DataMode): boolean {
  return mode === "LIVE";
}

/** Replay or mock data: must be labelled as synthetic/not live in the UI. */
export function isSyntheticMode(mode: DataMode): boolean {
  return mode === "REPLAY" || mode === "MOCK";
}

/** Provider is delivering (or able to deliver) data right now. */
export function isProviderHealthy(state: ProviderState): boolean {
  return state === "CONNECTED" || state === "DEGRADED";
}

/** Symbol is in an alerting state (shock or severe). */
export function isShockState(state: SymbolState): boolean {
  return state === "SHOCK" || state === "SEVERE";
}

export function isInterval(value: string): value is Interval {
  return (INTERVALS as readonly string[]).includes(value);
}

/** Format a shock score for display: "Shock score 0.86" (never a percent-confidence). */
export function formatShockScore(score: number | null | undefined): string {
  return score == null ? "Shock score -" : `Shock score ${score.toFixed(2)}`;
}
