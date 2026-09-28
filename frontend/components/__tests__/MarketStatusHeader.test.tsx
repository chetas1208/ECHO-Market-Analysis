import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DataMode, MarketStatus } from "@/types/market";

vi.mock("next/navigation", () => ({
  usePathname: () => "/",
  useRouter: () => ({ push: vi.fn() }),
}));

import { AppShell } from "../AppShell";

function status(mode: DataMode): MarketStatus {
  return {
    mode,
    providers: [],
    active_provider: null,
    subscribed_symbols: [],
    last_observation_at: null,
    queue: { depth: 0, capacity: 100, dropped: 0 },
    replay_finished: false,
    session: "REGULAR",
  };
}

const json = (body: unknown, init: ResponseInit = {}) =>
  new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
    ...init,
  });

/** Routes fetch by URL: /market/status is controlled by the test, /ready is always healthy. */
function mockFetch(marketStatus: () => Promise<Response>) {
  const fn = vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/api/v1/market/status")) return marketStatus();
    return Promise.resolve(json({ status: "ready", checks: {} }));
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

const badge = () => screen.getByRole("status", { name: /^Data mode:/ });

describe("AppShell market status header", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders OFFLINE before any status data arrives (and never LIVE)", () => {
    mockFetch(() => new Promise<Response>(() => {})); // never settles
    const { container } = render(
      <AppShell>
        <div />
      </AppShell>,
    );
    expect(badge().getAttribute("data-mode")).toBe("OFFLINE");
    expect(badge().textContent).toContain("OFFLINE");
    expect(container.querySelector(".topbar")?.textContent).not.toMatch(/\bLIVE\b/);
  });

  it("renders REPLAY when /market/status reports REPLAY", async () => {
    mockFetch(() => Promise.resolve(json(status("REPLAY"))));
    const { container } = render(
      <AppShell>
        <div />
      </AppShell>,
    );
    await waitFor(() => expect(badge().getAttribute("data-mode")).toBe("REPLAY"));
    expect(badge().textContent).toContain("REPLAY");
    expect(container.querySelector(".topbar")?.textContent).not.toMatch(/\bLIVE\b/);
    expect(document.body.textContent).not.toMatch(/\bLIVE\b/);
  });

  it("renders LIVE only when the backend reports LIVE", async () => {
    mockFetch(() => Promise.resolve(json(status("LIVE"))));
    render(
      <AppShell>
        <div />
      </AppShell>,
    );
    await waitFor(() => expect(badge().getAttribute("data-mode")).toBe("LIVE"));
    expect(badge().textContent).toContain("LIVE");
  });

  it("falls back to OFFLINE when the backend is unreachable", async () => {
    const fn = mockFetch(() => Promise.reject(new TypeError("Failed to fetch")));
    const { container } = render(
      <AppShell>
        <div />
      </AppShell>,
    );
    await waitFor(() => {
      expect(fn.mock.calls.some(([u]) => String(u).includes("/market/status"))).toBe(true);
    });
    await waitFor(() => expect(badge().getAttribute("data-mode")).toBe("OFFLINE"));
    expect(container.querySelector(".topbar")?.textContent).not.toMatch(/\bLIVE\b/);
  });

  it("falls back to OFFLINE on an HTTP error response", async () => {
    mockFetch(() =>
      Promise.resolve(
        json({ error: { code: "internal_error", message: "boom" } }, { status: 500 }),
      ),
    );
    render(
      <AppShell>
        <div />
      </AppShell>,
    );
    await waitFor(() => expect(badge().getAttribute("data-mode")).toBe("OFFLINE"));
  });

  it("keeps the API health indicator without implying live data", async () => {
    mockFetch(() => Promise.resolve(json(status("REPLAY"))));
    render(
      <AppShell>
        <div />
      </AppShell>,
    );
    await waitFor(() => expect(screen.getByTestId("api-health").textContent).toBe("API OK"));
    expect(screen.getByText(/^UTC /)).toBeInTheDocument();
  });
});
