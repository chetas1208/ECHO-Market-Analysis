/**
 * Typed client for the Day 3 world endpoints (docs/day3-contract.md):
 * GET /api/v1/world/status, GET /api/v1/events/{id}/sources and the filtered events list.
 * Reuses ApiError / API_BASE_URL / isAbortError from ./api and the same error-envelope parsing.
 */
import type { ApiErrorEnvelope } from "@/types/api";
import type { EventListResponse, SourceType } from "@/types/event";
import type { EventCategory, EventSourcesResponse, WorldStatus } from "@/types/world";
import { API_BASE_URL, ApiError, isAbortError } from "./api";

type Query = Record<string, string | number | undefined>;

export interface ListEventsWithFiltersParams {
  /** Omit or "all" for the unified feed. */
  sourceType?: SourceType | "all";
  eventType?: string;
  category?: EventCategory;
  /** Heuristic severity floor in [0, 1]. */
  severityMin?: number;
  start?: string | Date;
  end?: string | Date;
  limit?: number;
  offset?: number;
  signal?: AbortSignal;
}

function isErrorEnvelope(value: unknown): value is ApiErrorEnvelope {
  if (typeof value !== "object" || value === null || !("error" in value)) return false;
  const e = (value as { error: unknown }).error;
  return (
    typeof e === "object" && e !== null && typeof (e as { message?: unknown }).message === "string"
  );
}

/** Absolute URL under /api/v1; undefined query values are omitted, all values are encoded. */
export function buildWorldUrl(path: string, query: Query = {}): string {
  const url = new URL(`${API_BASE_URL}/api/v1${path}`);
  for (const [k, v] of Object.entries(query)) {
    if (v !== undefined) url.searchParams.set(k, String(v));
  }
  return url.toString();
}

const iso = (d: string | Date | undefined): string | undefined =>
  d instanceof Date ? d.toISOString() : d;

/** Absolute URL for the filtered events list. */
export function buildEventsFilterUrl(
  params: Omit<ListEventsWithFiltersParams, "signal"> = {},
): string {
  const { sourceType, eventType, category, severityMin, start, end, limit = 50, offset = 0 } =
    params;
  return buildWorldUrl("/events", {
    limit,
    offset,
    source_type: sourceType && sourceType !== "all" ? sourceType : undefined,
    event_type: eventType || undefined,
    category,
    severity_min: severityMin,
    start: iso(start),
    end: iso(end),
  });
}

async function worldRequest<T>(url: string, signal?: AbortSignal): Promise<T> {
  let res: Response;
  try {
    res = await fetch(url, { signal, headers: { Accept: "application/json" } });
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

export function getWorldStatus(signal?: AbortSignal): Promise<WorldStatus> {
  return worldRequest<WorldStatus>(buildWorldUrl("/world/status"), signal);
}

export function getEventSources(
  eventId: string,
  signal?: AbortSignal,
): Promise<EventSourcesResponse> {
  return worldRequest<EventSourcesResponse>(
    buildWorldUrl(`/events/${encodeURIComponent(eventId)}/sources`),
    signal,
  );
}

export function listEventsWithFilters(
  params: ListEventsWithFiltersParams = {},
): Promise<EventListResponse> {
  return worldRequest<EventListResponse>(buildEventsFilterUrl(params), params.signal);
}
