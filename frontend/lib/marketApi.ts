/**
 * Typed client for the /api/v1/market/* endpoints (see docs/day2-contract.md).
 * Reuses ApiError / base URL from ./api and the same error-envelope parsing.
 */
import type { ApiErrorEnvelope } from "@/types/api";
import type {
  BarsResponse,
  FeaturesResponse,
  MarketStatus,
  MarketSymbolsResponse,
  ShocksResponse,
} from "@/types/market";
import { API_BASE_URL, ApiError, isAbortError } from "./api";

export type BarInterval = "1m" | "5m" | "15m";

export interface GetBarsParams {
  interval?: BarInterval;
  start?: string | Date;
  end?: string | Date;
  limit?: number;
  signal?: AbortSignal;
}

type Query = Record<string, string | number | undefined>;

function isErrorEnvelope(value: unknown): value is ApiErrorEnvelope {
  if (typeof value !== "object" || value === null || !("error" in value)) return false;
  const e = (value as { error: unknown }).error;
  return (
    typeof e === "object" && e !== null && typeof (e as { message?: unknown }).message === "string"
  );
}

/** Builds the absolute URL for a market endpoint; undefined query values are omitted. */
export function buildMarketUrl(path: string, query: Query = {}): string {
  const url = new URL(`${API_BASE_URL}/api/v1/market${path}`);
  for (const [k, v] of Object.entries(query)) {
    if (v !== undefined) url.searchParams.set(k, String(v));
  }
  return url.toString();
}

async function marketRequest<T>(path: string, query?: Query, signal?: AbortSignal): Promise<T> {
  let res: Response;
  try {
    res = await fetch(buildMarketUrl(path, query), {
      signal,
      headers: { Accept: "application/json" },
    });
  } catch (err) {
    if (isAbortError(err)) throw err;
    throw new ApiError({
      message: `Cannot reach the ECHO API at ${API_BASE_URL}. Is the backend running?`,
      status: 0,
      code: "network_error",
    });
  }

  let body: unknown = null;
  try {
    body = await res.json();
  } catch (err) {
    if (isAbortError(err)) throw err;
  }

  if (!res.ok) {
    if (isErrorEnvelope(body)) {
      const e = body.error;
      throw new ApiError({
        message: e.message,
        status: res.status,
        code: e.code,
        requestId: e.request_id ?? null,
        details: e.details,
      });
    }
    throw new ApiError({
      message: `Unexpected response from API (HTTP ${res.status}).`,
      status: res.status,
      code: "unknown_error",
      requestId: res.headers.get("x-request-id"),
    });
  }
  if (body === null) {
    throw new ApiError({
      message: "API returned an empty or non-JSON response.",
      status: res.status,
      code: "unknown_error",
    });
  }
  return body as T;
}

const iso = (d: string | Date | undefined): string | undefined =>
  d instanceof Date ? d.toISOString() : d;

export function getMarketStatus(signal?: AbortSignal): Promise<MarketStatus> {
  return marketRequest<MarketStatus>("/status", undefined, signal);
}

export function getMarketSymbols(signal?: AbortSignal): Promise<MarketSymbolsResponse> {
  return marketRequest<MarketSymbolsResponse>("/symbols", undefined, signal);
}

export function getBars(symbol: string, params: GetBarsParams = {}): Promise<BarsResponse> {
  const { interval, start, end, limit, signal } = params;
  return marketRequest<BarsResponse>(
    `/bars/${encodeURIComponent(symbol)}`,
    { interval, start: iso(start), end: iso(end), limit },
    signal,
  );
}

export function getFeatures(symbol: string, signal?: AbortSignal): Promise<FeaturesResponse> {
  return marketRequest<FeaturesResponse>(
    `/features/${encodeURIComponent(symbol)}`,
    undefined,
    signal,
  );
}

export function getShocks(limit?: number, signal?: AbortSignal): Promise<ShocksResponse> {
  return marketRequest<ShocksResponse>("/shocks", { limit }, signal);
}
