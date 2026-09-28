/**
 * The single place in the frontend that performs HTTP requests to the ECHO API.
 * Base URL comes from NEXT_PUBLIC_API_URL (inlined at build time by Next).
 */
import type {
  ApiErrorCode,
  ApiErrorEnvelope,
  ReadyResponse,
} from "@/types/api";
import type { EchoEvent, EventListResponse } from "@/types/event";
import type { GraphProjection } from "@/types/graph";
import type {
  CauseInvestigation,
  CauseMode,
  ClusterShockList,
  MarketImpact,
} from "@/types/cause";
import type { ForecastPreview, ForecastingStatus } from "@/types/forecast";
import type {
  ForecastEvaluation,
  ForecastVintage,
  ForecastVintageList,
  PortfolioState,
  SimulatedTrade,
} from "@/types/ledger";
import type { BacktestList, BacktestRun, BacktestTrade } from "@/types/backtest";
import type { ExecutionStatus, PaperPosition } from "@/types/execution";
import type { OperationalStatus } from "@/types/ops";

export const DEFAULT_API_URL = "http://localhost:8100";

export const API_BASE_URL: string = (
  process.env.NEXT_PUBLIC_API_URL || DEFAULT_API_URL
).replace(/\/+$/, "");

const API_PREFIX = "/api/v1";

export type ClientErrorCode = ApiErrorCode | "network_error" | "unknown_error";

/** Typed error for every failed API call (HTTP error envelope, network failure, bad body). */
export class ApiError extends Error {
  readonly status: number;
  readonly code: ClientErrorCode;
  readonly requestId: string | null;
  readonly details: unknown;
  /** Parsed JSON body of a non-2xx response when it was not an error envelope. */
  readonly body: unknown;

  constructor(init: {
    message: string;
    status: number;
    code: ClientErrorCode;
    requestId?: string | null;
    details?: unknown;
    body?: unknown;
  }) {
    super(init.message);
    this.name = "ApiError";
    this.status = init.status;
    this.code = init.code;
    this.requestId = init.requestId ?? null;
    this.details = init.details;
    this.body = init.body;
  }
}

export function isAbortError(err: unknown): boolean {
  return err instanceof DOMException && err.name === "AbortError";
}

function isErrorEnvelope(value: unknown): value is ApiErrorEnvelope {
  if (typeof value !== "object" || value === null || !("error" in value)) return false;
  const e = (value as { error: unknown }).error;
  return (
    typeof e === "object" &&
    e !== null &&
    typeof (e as { message?: unknown }).message === "string"
  );
}

interface RequestOptions {
  signal?: AbortSignal;
  query?: Record<string, string | number | undefined>;
  method?: "GET" | "POST";
  body?: unknown;
}

async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const url = new URL(`${API_BASE_URL}${API_PREFIX}${path}`);
  for (const [k, v] of Object.entries(opts.query ?? {})) {
    if (v !== undefined) url.searchParams.set(k, String(v));
  }

  let res: Response;
  try {
    res = await fetch(url, {
      method: opts.method ?? "GET",
      signal: opts.signal,
      headers: {
        Accept: "application/json",
        ...(opts.body === undefined ? {} : { "Content-Type": "application/json" }),
      },
      body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
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
    // Non-JSON body; handled below.
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
      body,
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

export function listEvents(
  params: { limit?: number; offset?: number; signal?: AbortSignal } = {},
): Promise<EventListResponse> {
  const { limit = 50, offset = 0, signal } = params;
  return request<EventListResponse>("/events", { signal, query: { limit, offset } });
}

export function getEvent(id: string, signal?: AbortSignal): Promise<EchoEvent> {
  return request<EchoEvent>(`/events/${encodeURIComponent(id)}`, { signal });
}

export function getEventGraph(
  id: string,
  params: { snapshotId?: string; maxDepth?: number; limit?: number; signal?: AbortSignal } = {},
): Promise<GraphProjection> {
  return request<GraphProjection>(`/events/${encodeURIComponent(id)}/graph`, {
    signal: params.signal,
    query: {
      snapshot_id: params.snapshotId,
      max_depth: params.maxDepth ?? 3,
      limit: params.limit ?? 25,
    },
  });
}

export function investigateMarketShock(
  id: string,
  params: { mode?: CauseMode; dataCutoffAt?: string; snapshotId?: string; signal?: AbortSignal } = {},
): Promise<CauseInvestigation> {
  return request<CauseInvestigation>(`/investigations/market-shock/${encodeURIComponent(id)}`, {
    method: "POST",
    signal: params.signal,
    query: {
      mode: params.mode ?? "REALTIME",
      data_cutoff_at: params.dataCutoffAt,
      snapshot_id: params.snapshotId,
    },
  });
}

export function getInvestigation(id: string, signal?: AbortSignal): Promise<CauseInvestigation> {
  return request<CauseInvestigation>(`/investigations/${encodeURIComponent(id)}`, { signal });
}

export function getEventMarketImpact(
  id: string,
  params: { dataCutoffAt?: string; snapshotId?: string; signal?: AbortSignal } = {},
): Promise<MarketImpact> {
  return request<MarketImpact>(`/events/${encodeURIComponent(id)}/market-impact`, {
    signal: params.signal,
    query: { data_cutoff_at: params.dataCutoffAt, snapshot_id: params.snapshotId },
  });
}

export function getMarketClusters(params: { signal?: AbortSignal } = {}): Promise<ClusterShockList> {
  return request<ClusterShockList>("/market/clusters", { signal: params.signal });
}

export function getForecastingStatus(signal?: AbortSignal): Promise<ForecastingStatus> {
  return request<ForecastingStatus>("/forecasting/status", { signal });
}

export function previewForecast(
  payload: { event_id: string; symbol: string; graph_snapshot_id?: string; data_cutoff_at?: string },
  signal?: AbortSignal,
): Promise<ForecastPreview> {
  return request<ForecastPreview>("/forecasts/preview", {
    method: "POST",
    signal,
    body: payload,
  });
}

export function createForecastVintage(payload: {
  preview: ForecastPreview;
  config_hash: string;
  forecasting_engine_version?: string;
  idempotency_key?: string;
}): Promise<ForecastVintage> {
  return request<ForecastVintage>("/forecasts", { method: "POST", body: payload });
}

export function listForecastVintages(params: {
  symbol?: string;
  event_id?: string;
  signal?: AbortSignal;
} = {}): Promise<ForecastVintageList> {
  return request<ForecastVintageList>("/forecasts", {
    signal: params.signal,
    query: { symbol: params.symbol, event_id: params.event_id },
  });
}

export function getForecastVintage(id: string, signal?: AbortSignal): Promise<ForecastVintage> {
  return request<ForecastVintage>(`/forecasts/${encodeURIComponent(id)}`, { signal });
}

export function getForecastEvaluation(id: string, signal?: AbortSignal): Promise<{ items: ForecastEvaluation[] }> {
  return request<{ items: ForecastEvaluation[] }>(`/forecasts/${encodeURIComponent(id)}/evaluation`, { signal });
}

export function simulateForecast(id: string, body: Record<string, unknown>): Promise<SimulatedTrade> {
  return request<SimulatedTrade>(`/forecasts/${encodeURIComponent(id)}/simulate`, { method: "POST", body });
}

export function getSimulatedPortfolio(signal?: AbortSignal): Promise<PortfolioState> {
  return request<PortfolioState>("/portfolio/simulated", { signal });
}

export function listBacktests(signal?: AbortSignal): Promise<BacktestList> {
  return request<BacktestList>("/backtests", { signal });
}

export function getBacktest(id: string, signal?: AbortSignal): Promise<BacktestRun> {
  return request<BacktestRun>(`/backtests/${encodeURIComponent(id)}`, { signal });
}

export function getBacktestTrades(id: string, signal?: AbortSignal): Promise<BacktestTrade[]> {
  return request<BacktestTrade[]>(`/backtests/${encodeURIComponent(id)}/trades`, { signal });
}

export function getExecutionStatus(signal?: AbortSignal): Promise<ExecutionStatus> {
  return request<ExecutionStatus>("/execution/status", { signal });
}

export function getOperationalStatus(signal?: AbortSignal): Promise<OperationalStatus> {
  return request<OperationalStatus>("/ops/status", { signal });
}

export function getPaperPositions(signal?: AbortSignal): Promise<PaperPosition[]> {
  return request<PaperPosition[]>("/paper/positions", { signal });
}

export function getBacktestResearch(signal?: AbortSignal): Promise<{ trials_count: number; families: Record<string, { total_return: number; sharpe: number | null; max_drawdown: number; trades: number; status: string }>; ablations: Record<string, { total_return: number; sharpe: number | null; max_drawdown: number; trades: number; status: string }>; robustness: Record<string, { total_return: number; sharpe: number | null; max_drawdown: number; trades: number; status: string }> }> {
  return request("/backtests/research", { signal });
}

function isReadyBody(value: unknown): value is ReadyResponse {
  if (typeof value !== "object" || value === null) return false;
  const v = value as { status?: unknown; checks?: unknown };
  return (
    (v.status === "ready" || v.status === "not_ready") &&
    typeof v.checks === "object" &&
    v.checks !== null
  );
}

/**
 * Readiness probe. The backend answers 503 with a NON-envelope body
 * `{"status":"not_ready","checks":{...}}` when a dependency is down; that is a valid
 * result (returned, not thrown). Other failures still throw ApiError.
 */
export async function getReady(signal?: AbortSignal): Promise<ReadyResponse> {
  try {
    return await request<ReadyResponse>("/ready", { signal });
  } catch (err) {
    if (err instanceof ApiError && err.status === 503 && isReadyBody(err.body)) {
      return err.body;
    }
    throw err;
  }
}
