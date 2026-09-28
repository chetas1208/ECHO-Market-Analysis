import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { API_BASE_URL, ApiError } from "../api";
import {
  buildEventsFilterUrl,
  getEventSources,
  getWorldStatus,
  listEventsWithFilters,
} from "../worldApi";
import { isWorldLive, safeExternalUrl, severityBucket } from "@/types/world";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  vi.unstubAllGlobals();
});

const calledUrl = (i = 0) => new URL(String(fetchMock.mock.calls[i]![0]));

describe("worldApi URL building", () => {
  it("getWorldStatus hits /world/status and passes the signal", async () => {
    fetchMock.mockImplementation(async () => jsonResponse({ mode: "OFFLINE" }));
    const ac = new AbortController();
    await getWorldStatus(ac.signal);
    expect(String(fetchMock.mock.calls[0]![0])).toBe(`${API_BASE_URL}/api/v1/world/status`);
    expect(fetchMock.mock.calls[0]![1].signal).toBe(ac.signal);
  });

  it("getEventSources encodes the event id", async () => {
    fetchMock.mockImplementation(async () => jsonResponse({ items: [], total: 0 }));
    await getEventSources("evt_a/b?c#d");
    expect(String(fetchMock.mock.calls[0]![0])).toBe(
      `${API_BASE_URL}/api/v1/events/evt_a%2Fb%3Fc%23d/sources`,
    );
  });

  it("listEventsWithFilters defaults and omits undefined / all", () => {
    const u = new URL(buildEventsFilterUrl({ sourceType: "all" }));
    expect(u.pathname).toBe("/api/v1/events");
    expect([...u.searchParams.keys()].sort()).toEqual(["limit", "offset"]);
    expect(u.searchParams.get("limit")).toBe("50");
    expect(u.searchParams.get("offset")).toBe("0");
  });

  it("sends every filter, converting Dates to ISO and encoding values", async () => {
    fetchMock.mockImplementation(async () => jsonResponse({ items: [], total: 0 }));
    await listEventsWithFilters({
      sourceType: "world",
      eventType: "shipping disruption&x=1",
      category: "supply_chain",
      severityMin: 0.5,
      start: new Date("2026-09-16T09:00:00Z"),
      end: "2026-09-17T00:00:00+00:00",
      limit: 10,
      offset: 20,
    });
    const u = calledUrl();
    expect(u.searchParams.get("source_type")).toBe("world");
    expect(u.searchParams.get("event_type")).toBe("shipping disruption&x=1");
    expect(u.searchParams.get("category")).toBe("supply_chain");
    expect(u.searchParams.get("severity_min")).toBe("0.5");
    expect(u.searchParams.get("start")).toBe("2026-09-16T09:00:00.000Z");
    expect(u.searchParams.get("end")).toBe("2026-09-17T00:00:00+00:00");
    expect(u.searchParams.get("limit")).toBe("10");
    expect(u.searchParams.get("offset")).toBe("20");
    expect(u.searchParams.has("x")).toBe(false);
    expect(String(fetchMock.mock.calls[0]![0])).toContain("shipping+disruption%26x%3D1");
  });

  it("keeps severityMin 0 (falsy but valid)", () => {
    const u = new URL(buildEventsFilterUrl({ severityMin: 0 }));
    expect(u.searchParams.get("severity_min")).toBe("0");
  });
});

describe("worldApi error passthrough", () => {
  it("throws ApiError from the error envelope", async () => {
    fetchMock.mockImplementation(async () =>
      jsonResponse(
        { error: { code: "not_found", message: "Event not found", request_id: "r1" } },
        404,
      ),
    );
    const err = await getEventSources("evt_missing").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(404);
    expect((err as ApiError).code).toBe("not_found");
    expect((err as ApiError).requestId).toBe("r1");
    expect((err as ApiError).message).toBe("Event not found");
  });

  it("maps network failure to network_error and rethrows aborts", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("fetch failed"));
    const err = await getWorldStatus().catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).code).toBe("network_error");
    expect((err as ApiError).status).toBe(0);

    const abort = new DOMException("aborted", "AbortError");
    fetchMock.mockRejectedValueOnce(abort);
    await expect(getWorldStatus()).rejects.toBe(abort);
  });

  it("non-envelope error and empty body become unknown_error", async () => {
    fetchMock.mockImplementationOnce(async () => new Response("boom", { status: 500 }));
    const e1 = await listEventsWithFilters().catch((e: unknown) => e);
    expect((e1 as ApiError).code).toBe("unknown_error");
    expect((e1 as ApiError).status).toBe(500);

    fetchMock.mockImplementationOnce(async () => new Response("not json", { status: 200 }));
    const e2 = await getWorldStatus().catch((e: unknown) => e);
    expect((e2 as ApiError).code).toBe("unknown_error");
  });
});

describe("safeExternalUrl", () => {
  it("allows absolute http and https", () => {
    expect(safeExternalUrl("https://example.com/a?b=1")).toBe("https://example.com/a?b=1");
    expect(safeExternalUrl("http://example.com")).toBe("http://example.com");
  });
  it("blocks javascript:, data:, other schemes", () => {
    expect(safeExternalUrl("javascript:alert(1)")).toBeNull();
    expect(safeExternalUrl("  JavaScript:alert(1)")).toBeNull();
    expect(safeExternalUrl("data:text/html,<script>alert(1)</script>")).toBeNull();
    expect(safeExternalUrl("ftp://example.com/f")).toBeNull();
    expect(safeExternalUrl("file:///etc/passwd")).toBeNull();
  });
  it("blocks relative, protocol-relative, garbage, empty and nullish", () => {
    expect(safeExternalUrl("/relative/path")).toBeNull();
    expect(safeExternalUrl("//evil.example.com")).toBeNull();
    expect(safeExternalUrl("example.com")).toBeNull();
    expect(safeExternalUrl("not a url")).toBeNull();
    expect(safeExternalUrl("http://")).toBeNull();
    expect(safeExternalUrl("")).toBeNull();
    expect(safeExternalUrl("   ")).toBeNull();
    expect(safeExternalUrl(null)).toBeNull();
    expect(safeExternalUrl(undefined)).toBeNull();
  });
});

describe("severityBucket", () => {
  it("matches backend thresholds at the edges", () => {
    expect(severityBucket(1)).toBe("HIGH");
    expect(severityBucket(0.7)).toBe("HIGH");
    expect(severityBucket(0.6999)).toBe("ELEVATED");
    expect(severityBucket(0.5)).toBe("ELEVATED");
    expect(severityBucket(0.4999)).toBe("MODERATE");
    expect(severityBucket(0.3)).toBe("MODERATE");
    expect(severityBucket(0.2999)).toBe("LOW");
    expect(severityBucket(0)).toBe("LOW");
  });
});

describe("isWorldLive", () => {
  it("is true only for LIVE", () => {
    expect(isWorldLive("LIVE")).toBe(true);
    expect(isWorldLive("REPLAY")).toBe(false);
    expect(isWorldLive("OFFLINE")).toBe(false);
    expect(isWorldLive(null)).toBe(false);
    expect(isWorldLive(undefined)).toBe(false);
  });
});
