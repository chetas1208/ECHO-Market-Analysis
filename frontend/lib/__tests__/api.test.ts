import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, getEvent, getReady } from "@/lib/api";

function mockFetch(status: number, body: unknown, headers: Record<string, string> = {}) {
  const fn = vi.fn().mockResolvedValue(
    new Response(typeof body === "string" ? body : JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json", ...headers },
    }),
  );
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("api client", () => {
  it("parses the error envelope into a typed ApiError", async () => {
    mockFetch(404, {
      error: { code: "not_found", message: "Event 'x' not found", request_id: "rid-1" },
    });
    const err = await getEvent("x").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    const apiErr = err as ApiError;
    expect(apiErr.status).toBe(404);
    expect(apiErr.code).toBe("not_found");
    expect(apiErr.message).toBe("Event 'x' not found");
    expect(apiErr.requestId).toBe("rid-1");
  });

  it("passes through method_not_allowed envelope codes", async () => {
    mockFetch(405, {
      error: { code: "method_not_allowed", message: "Method Not Allowed", request_id: "r" },
    });
    await expect(getEvent("x")).rejects.toMatchObject({ code: "method_not_allowed", status: 405 });
  });

  it("returns the non-envelope 503 not_ready body from getReady", async () => {
    mockFetch(503, { status: "not_ready", checks: { database: "error" } });
    await expect(getReady()).resolves.toEqual({
      status: "not_ready",
      checks: { database: "error" },
    });
  });

  it("returns ready body on 200", async () => {
    mockFetch(200, { status: "ready", checks: { database: "ok" } });
    await expect(getReady()).resolves.toEqual({ status: "ready", checks: { database: "ok" } });
  });

  it("still throws unknown_error for a 503 without a ready body", async () => {
    mockFetch(503, "upstream down");
    await expect(getReady()).rejects.toMatchObject({ code: "unknown_error", status: 503 });
  });

  it("throws the envelope error from getReady for non-ready failures", async () => {
    mockFetch(500, { error: { code: "internal_error", message: "boom", request_id: "r" } });
    await expect(getReady()).rejects.toMatchObject({ code: "internal_error", status: 500 });
  });

  it("maps a fetch rejection to network_error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    const err = await getEvent("x").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ code: "network_error", status: 0 });
  });
});
