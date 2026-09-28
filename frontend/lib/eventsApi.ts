/**
 * Events feed client with the optional `source_type` filter (`GET /api/v1/events?source_type=market`).
 * `listEvents` in ./api predates the filter and is owned elsewhere, so this adds a sibling function
 * that reuses its exports (ApiError / API_BASE_URL / isAbortError) and the same error-envelope parsing.
 */
import type { ApiErrorEnvelope } from "@/types/api";
import type { EventListResponse, SourceType } from "@/types/event";
import { API_BASE_URL, ApiError, isAbortError } from "./api";

export type EventSourceFilter = SourceType | "all";

export interface ListEventsFilteredParams {
  limit?: number;
  offset?: number;
  /** Omit or "all" for the unified feed; otherwise sent as the `source_type` query param. */
  sourceType?: EventSourceFilter;
  signal?: AbortSignal;
}

function isErrorEnvelope(value: unknown): value is ApiErrorEnvelope {
  if (typeof value !== "object" || value === null || !("error" in value)) return false;
  const e = (value as { error: unknown }).error;
  return (
    typeof e === "object" && e !== null && typeof (e as { message?: unknown }).message === "string"
  );
}

/** Absolute URL for the events list; `source_type` is omitted for "all". */
export function buildEventsUrl(params: Omit<ListEventsFilteredParams, "signal"> = {}): string {
  const { limit = 50, offset = 0, sourceType } = params;
  const url = new URL(`${API_BASE_URL}/api/v1/events`);
  url.searchParams.set("limit", String(limit));
  url.searchParams.set("offset", String(offset));
  if (sourceType && sourceType !== "all") url.searchParams.set("source_type", sourceType);
  return url.toString();
}

export async function listEventsFiltered(
  params: ListEventsFilteredParams = {},
): Promise<EventListResponse> {
  let res: Response;
  try {
    res = await fetch(buildEventsUrl(params), {
      signal: params.signal,
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
  return body as EventListResponse;
}
