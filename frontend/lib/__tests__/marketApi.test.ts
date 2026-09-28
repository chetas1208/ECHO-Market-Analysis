import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { API_BASE_URL, ApiError } from "../api";
import {
  buildMarketUrl,
  getBars,
  getFeatures,
  getMarketStatus,
  getMarketSymbols,
  getShocks,
} from "../marketApi";
import { usePolling } from "../usePolling";

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
  vi.useRealTimers();
});

const calledUrl = (i = 0) => new URL(String(fetchMock.mock.calls[i]![0]));

describe("marketApi URL building", () => {
  it("builds base + prefix and omits undefined params", () => {
    expect(buildMarketUrl("/status")).toBe(`${API_BASE_URL}/api/v1/market/status`);
    expect(buildMarketUrl("/shocks", { limit: undefined })).toBe(
      `${API_BASE_URL}/api/v1/market/shocks`,
    );
  });

  it("status / symbols hit the right paths and pass the signal", async () => {
    fetchMock.mockImplementation(async () => jsonResponse({ ok: 1 }));
    const ac = new AbortController();
    await getMarketStatus(ac.signal);
    await getMarketSymbols();
    expect(calledUrl(0).pathname).toBe("/api/v1/market/status");
    expect(calledUrl(1).pathname).toBe("/api/v1/market/symbols");
    expect(fetchMock.mock.calls[0]![1].signal).toBe(ac.signal);
  });

  it("getBars encodes symbol and sets interval/start/end/limit", async () => {
    fetchMock.mockImplementation(async () => jsonResponse({ items: [] }));
    await getBars("BRK/B", {
      interval: "5m",
      start: "2026-01-02T14:30:00Z",
      end: new Date("2026-01-02T15:00:00Z"),
      limit: 120,
    });
    const u = calledUrl();
    expect(u.pathname).toBe("/api/v1/market/bars/BRK%2FB");
    expect(u.searchParams.get("interval")).toBe("5m");
    expect(u.searchParams.get("start")).toBe("2026-01-02T14:30:00Z");
    expect(u.searchParams.get("end")).toBe("2026-01-02T15:00:00.000Z");
    expect(u.searchParams.get("limit")).toBe("120");
  });

  it("getBars with no params sends no query string", async () => {
    fetchMock.mockImplementation(async () => jsonResponse({ items: [] }));
    await getBars("NVDA");
    expect(calledUrl().search).toBe("");
  });

  it("getFeatures and getShocks", async () => {
    fetchMock.mockImplementation(async () => jsonResponse({}));
    await getFeatures("NVDA");
    await getShocks(25);
    await getShocks();
    expect(calledUrl(0).pathname).toBe("/api/v1/market/features/NVDA");
    expect(calledUrl(1).searchParams.get("limit")).toBe("25");
    expect(calledUrl(2).search).toBe("");
  });
});

describe("marketApi errors", () => {
  it("passes through the error envelope as ApiError", async () => {
    fetchMock.mockImplementation(async () =>
      jsonResponse(
        { error: { code: "not_found", message: "Unknown symbol", request_id: "r1" } },
        404,
      ),
    );
    const err = await getFeatures("ZZZZ").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({
      status: 404,
      code: "not_found",
      message: "Unknown symbol",
      requestId: "r1",
    });
  });

  it("maps non-envelope HTTP errors to unknown_error", async () => {
    fetchMock.mockImplementation(async () => new Response("boom", { status: 502 }));
    await expect(getMarketStatus()).rejects.toMatchObject({ status: 502, code: "unknown_error" });
  });

  it("maps network failure to network_error and rethrows aborts untouched", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("fetch failed"));
    await expect(getMarketStatus()).rejects.toMatchObject({ code: "network_error", status: 0 });
    fetchMock.mockRejectedValueOnce(new DOMException("aborted", "AbortError"));
    await expect(getMarketStatus()).rejects.toMatchObject({ name: "AbortError" });
  });

  it("rejects an empty 200 body", async () => {
    fetchMock.mockImplementation(async () => new Response("", { status: 200 }));
    await expect(getMarketSymbols()).rejects.toMatchObject({ code: "unknown_error" });
  });
});

describe("usePolling", () => {
  const flush = () => act(async () => {});

  function setHidden(hidden: boolean) {
    Object.defineProperty(document, "hidden", { configurable: true, get: () => hidden });
    document.dispatchEvent(new Event("visibilitychange"));
  }
  afterEach(() => setHidden(false));

  it("polls on an interval, updates data and lastUpdated", async () => {
    vi.useFakeTimers();
    let n = 0;
    const fetcher = vi.fn(async () => ++n);
    const { result } = renderHook(() => usePolling(fetcher, 1000));
    expect(result.current.loading).toBe(true);
    await flush();
    expect(result.current).toMatchObject({ data: 1, loading: false, error: null });
    expect(result.current.lastUpdated).toBeInstanceOf(Date);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(result.current.data).toBe(2);
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("keeps last good data on error and clears error on recovery", async () => {
    vi.useFakeTimers();
    const fetcher = vi
      .fn<(s: AbortSignal) => Promise<number>>()
      .mockResolvedValueOnce(7)
      .mockRejectedValueOnce(new Error("down"))
      .mockResolvedValue(9);
    const { result } = renderHook(() => usePolling(fetcher, 1000));
    await flush();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(result.current.data).toBe(7);
    expect(result.current.error).toBeInstanceOf(ApiError);
    expect(result.current.error?.message).toBe("down");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(result.current.data).toBe(9);
    expect(result.current.error).toBeNull();
  });

  it("never overlaps requests (refresh while in flight is a no-op)", async () => {
    vi.useFakeTimers();
    let resolve!: (v: number) => void;
    const fetcher = vi.fn(() => new Promise<number>((r) => (resolve = r)));
    const { result } = renderHook(() => usePolling(fetcher, 1000));
    await flush();
    act(() => result.current.refresh());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(fetcher).toHaveBeenCalledTimes(1);
    await act(async () => resolve(1));
    expect(result.current.data).toBe(1);
    act(() => result.current.refresh());
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("pauses while hidden and resumes immediately when visible", async () => {
    vi.useFakeTimers();
    const fetcher = vi.fn(async () => 1);
    renderHook(() => usePolling(fetcher, 1000));
    await flush();
    setHidden(true);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(fetcher).toHaveBeenCalledTimes(1);
    setHidden(false);
    await flush();
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("aborts in-flight on unmount and stops polling", async () => {
    vi.useFakeTimers();
    let signal!: AbortSignal;
    const fetcher = vi.fn((s: AbortSignal) => {
      signal = s;
      return new Promise<number>(() => {});
    });
    const { unmount } = renderHook(() => usePolling(fetcher, 1000));
    await flush();
    expect(signal.aborted).toBe(false);
    unmount();
    expect(signal.aborted).toBe(true);
    await vi.advanceTimersByTimeAsync(5000);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
});
