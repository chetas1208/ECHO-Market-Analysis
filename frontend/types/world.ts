/** Day 3 world-monitor types (see docs/day3-contract.md, API section). */

/** What the UI shows for the world feed. Replay must never masquerade as LIVE. */
export type WorldMode = "LIVE" | "REPLAY" | "OFFLINE";

export type WorldProviderState =
  | "UNCONFIGURED"
  | "CONNECTING"
  | "HEALTHY"
  | "DEGRADED"
  | "STALE"
  | "ERROR"
  | "REPLAY";

export type WorldProviderName = "world_monitor" | "replay";

export interface WorldProviderHealth {
  provider: WorldProviderName;
  configured: boolean;
  state: WorldProviderState;
  mode: WorldMode;
  /** ISO 8601 (Z) or null. */
  last_success_at: string | null;
  last_event_at: string | null;
  events_received: number;
  malformed_events: number;
  last_error: string | null;
  poll_interval_s: number | null;
  retry_after_until: string | null;
}

export type TextAnalyzerStatus = "AVAILABLE" | "LOADING" | "UNAVAILABLE" | "DISABLED";

/** Runtime counters; keys are additive, so unknown ones are tolerated. */
export interface WorldCounters {
  received?: number;
  created?: number;
  merged?: number;
  duplicates?: number;
  rejected?: number;
  last_event_at?: string | null;
  [key: string]: number | string | null | undefined;
}

/** GET /api/v1/world/status */
export interface WorldStatus {
  mode: WorldMode;
  provider: WorldProviderHealth;
  counters: WorldCounters;
  text_analyzer: TextAnalyzerStatus;
}

/** One evidence row from GET /api/v1/events/{id}/sources. */
export interface EventSource {
  provider: string;
  source_name: string;
  source_group: string | null;
  source_url: string | null;
  headline: string | null;
  published_at: string | null;
  retrieved_at: string;
  is_independent: boolean;
  syndicated_from: string | null;
  /** Heuristic reliability in [0, 1], when supplied. */
  reliability: number | null;
}

export interface EventSourcesResponse {
  items: EventSource[];
  total: number;
}

/** UI filter groups (backend CATEGORY_GROUP). */
export type EventCategory =
  | "geopolitics"
  | "energy"
  | "supply_chain"
  | "technology"
  | "macro"
  | "other";

export type SeverityBucket = "HIGH" | "ELEVATED" | "MODERATE" | "LOW";

/** Must match backend `severity_bucket` (app/world/scoring/severity.py). */
export function severityBucket(score: number): SeverityBucket {
  if (score >= 0.7) return "HIGH";
  if (score >= 0.5) return "ELEVATED";
  if (score >= 0.3) return "MODERATE";
  return "LOW";
}

/**
 * Returns the URL only if it is an absolute http(s) URL; otherwise null
 * (blocks javascript:, data:, relative and malformed values).
 */
export function safeExternalUrl(url: string | null | undefined): string | null {
  if (typeof url !== "string") return null;
  const trimmed = url.trim();
  if (!trimmed) return null;
  let parsed: URL;
  try {
    parsed = new URL(trimmed);
  } catch {
    return null;
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return null;
  if (!parsed.hostname) return null;
  return trimmed;
}

/** True only for a genuinely live feed (never for REPLAY or OFFLINE). */
export function isWorldLive(mode: WorldMode | null | undefined): boolean {
  return mode === "LIVE";
}
