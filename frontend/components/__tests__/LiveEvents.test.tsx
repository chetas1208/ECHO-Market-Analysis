import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { EchoEvent } from "@/types/event";
import { EventDetailView } from "../EventDetailView";
import { LiveEvents } from "../LiveEvents";

const replace = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace, push: vi.fn() }) }));

const base: EchoEvent = {
  id: "evt_world_1",
  timestamp: "2026-09-20T09:00:00Z",
  source_type: "world",
  event_type: "geopolitical_shipping_disruption",
  title: "Strait Test disruption",
  summary: null,
  entities: [],
  companies: ["XOM"],
  locations: [],
  economic_channels: { oil_supply: -0.8 },
  severity: 0.8,
  novelty: 0.5,
  corroboration: 0.6,
  confidence: 0.91,
  source_refs: [],
  metadata: {},
  is_mock: false,
  created_at: "2026-09-20T09:00:00Z",
  ingested_at: "2026-09-20T09:00:01Z",
};
const shock: EchoEvent = {
  ...base,
  id: "evt_mkt_nvda_202609201500_neg",
  source_type: "market",
  event_type: "market_shock",
  title: "NVDA abnormal downside move",
  companies: ["NVDA"],
  economic_channels: {},
  confidence: 0.8,
  source_refs: [{ name: "replay" }],
  metadata: {
    direction: "negative",
    shock_score: 0.864,
    calibrated: false,
    return_5m: -0.045,
    return_z: -4.2,
    volume_z: 7.5,
    volatility_z: 3.1,
    sector_residual: -0.043,
    market_residual: -0.044,
    provider: "replay",
    components: { ret: 1, volume: 0.9 },
  },
};

const page = (items: EchoEvent[], total = items.length) => ({ items, total, limit: 20, offset: 0 });
const json = (body: unknown, status = 200) =>
  Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }));

let fetchMock: ReturnType<typeof vi.fn>;
const urls = () => fetchMock.mock.calls.map((c) => new URL(String(c[0])));
/** Calls to the events list only (the world-status chip polls /world/status separately). */
const eventCalls = () => urls().filter((u) => u.pathname.endsWith("/events"));

beforeEach(() => {
  replace.mockClear();
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("LiveEvents unified feed", () => {
  it("renders world and market shock events in one list with badge and shock score", async () => {
    fetchMock.mockImplementation(() => json(page([shock, base])));
    render(<LiveEvents />);

    expect(await screen.findByText("NVDA abnormal downside move")).toBeInTheDocument();
    expect(screen.getByText("Strait Test disruption")).toBeInTheDocument();
    expect(screen.getAllByRole("list", { name: /Events, newest first/ })).toHaveLength(1);
    expect(screen.getByText("MARKET SHOCK")).toBeInTheDocument();
    expect(screen.getByTestId("shock-score")).toHaveTextContent("Shock score 0.86");
    expect(screen.getByTestId("shock-score")).not.toHaveTextContent("%");
    expect(urls()[0]?.searchParams.get("source_type")).toBeNull();
  });

  it("changing the filter changes the source_type request param", async () => {
    fetchMock.mockImplementation((url: string) =>
      json(page(new URL(String(url)).searchParams.get("source_type") === "market" ? [shock] : [shock, base])),
    );
    render(<LiveEvents />);
    await screen.findByText("Strait Test disruption");
    expect(screen.getByRole("button", { name: "All" })).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(screen.getByRole("button", { name: "Market shocks" }));

    await waitFor(() => expect(urls().some((u) => u.searchParams.get("source_type") === "market")).toBe(true));
    await waitFor(() => expect(screen.queryByText("Strait Test disruption")).not.toBeInTheDocument());
    expect(screen.getByText("NVDA abnormal downside move")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Market shocks" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Market shocks" })).toHaveFocus();

    fireEvent.click(screen.getByRole("button", { name: "World" }));
    await waitFor(() => expect(urls().some((u) => u.searchParams.get("source_type") === "world")).toBe(true));
    fireEvent.click(screen.getByRole("button", { name: "Financial" }));
    await waitFor(() => expect(urls().some((u) => u.searchParams.get("source_type") === "financial")).toBe(true));
  });

  it("filters client-side when the backend ignores source_type", async () => {
    fetchMock.mockImplementation(() => json(page([shock, base], 2)));
    render(<LiveEvents />);
    await screen.findByText("Strait Test disruption");

    fireEvent.click(screen.getByRole("button", { name: "World" }));

    await waitFor(() => expect(screen.queryByText("NVDA abnormal downside move")).not.toBeInTheDocument());
    expect(screen.getByText("Strait Test disruption")).toBeInTheDocument();
    expect(screen.getByText(/filtered locally/)).toBeInTheDocument();
  });

  it("shows the empty state (filter-specific once filtered)", async () => {
    fetchMock.mockImplementation(() => json(page([])));
    render(<LiveEvents />);
    expect(await screen.findByText("No events returned")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Market shocks" }));
    expect(await screen.findByText("No market shocks returned")).toBeInTheDocument();
  });

  it("shows loading, then the error state with retry", async () => {
    let fail = true;
    fetchMock.mockImplementation(() =>
      fail ? json({ error: { code: "internal_error", message: "boom", request_id: "r1" } }, 500) : json(page([base])),
    );
    render(<LiveEvents />);
    expect(screen.getByRole("status", { busy: true })).toHaveAttribute("aria-busy", "true");
    expect(await screen.findByTestId("error-state")).toHaveTextContent("boom");

    fail = false;
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("Strait Test disruption")).toBeInTheDocument();
  });

  it("auto-refreshes every 10 s without replacing the list by a loading state", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    let n = 0;
    fetchMock.mockImplementation(() => json(page(n++ === 0 ? [base] : [shock, base])));
    render(<LiveEvents />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(screen.getByText("Strait Test disruption")).toBeInTheDocument();
    expect(eventCalls()).toHaveLength(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(9_000);
    });
    expect(eventCalls()).toHaveLength(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_500);
    });
    expect(eventCalls()).toHaveLength(2);
    expect(screen.queryByRole("status", { busy: true })).not.toBeInTheDocument();
    expect(screen.getByText("NVDA abnormal downside move")).toBeInTheDocument();
    expect(screen.getByText("Strait Test disruption")).toBeInTheDocument();
  });

  it("keeps the last rows and notes a failed refresh", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    let n = 0;
    fetchMock.mockImplementation(() =>
      n++ === 0 ? json(page([base])) : json({ error: { code: "internal_error", message: "down" } }, 500),
    );
    render(<LiveEvents />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_500);
    });
    expect(screen.getByText("Strait Test disruption")).toBeInTheDocument();
    expect(screen.getByText(/Refresh failed \(down\)/)).toBeInTheDocument();
    expect(screen.queryByTestId("error-state")).not.toBeInTheDocument();
  });
});

describe("EventDetailView market shock metrics", () => {
  it("renders the metrics table with the heuristic label and no percent confidence", async () => {
    fetchMock.mockImplementation(() => json(shock));
    render(<EventDetailView id={shock.id} />);

    const section = await screen.findByTestId("shock-metrics");
    expect(screen.getByTestId("shock-metrics-note")).toHaveTextContent(
      "Heuristic score — not a calibrated probability",
    );
    for (const key of [
      "shock_score", "return_5m", "return_z", "volume_z", "volatility_z",
      "sector_residual", "market_residual", "provider", "components",
    ]) {
      expect(section).toHaveTextContent(key);
    }
    expect(section).toHaveTextContent("0.864");
    expect(section).toHaveTextContent("-4.2");
    expect(section).toHaveTextContent("replay");
    expect(section).toHaveTextContent("ret 1 · volume 0.9");
    expect(screen.queryByRole("meter", { name: "Confidence" })).not.toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/confidence[^a-z]*\d+\s*%/i);
  });

  it("does not render the metrics table for world events", async () => {
    fetchMock.mockImplementation(() => json(base));
    render(<EventDetailView id={base.id} />);
    expect(await screen.findByRole("heading", { name: base.title })).toBeInTheDocument();
    expect(screen.queryByTestId("shock-metrics")).not.toBeInTheDocument();
  });
});

const statusBody = (mode: "LIVE" | "REPLAY" | "OFFLINE", provider: "replay" | "world_monitor" = "replay") => ({
  mode,
  provider: {
    provider,
    configured: true,
    state: mode === "REPLAY" ? "REPLAY" : "HEALTHY",
    mode,
    last_success_at: null,
    last_event_at: null,
    events_received: 0,
    malformed_events: 0,
    last_error: null,
    poll_interval_s: null,
    retry_after_until: null,
  },
  counters: {},
  text_analyzer: "DISABLED",
});

/** Routes /world/status to `status` (or a 500) and everything else to the events page. */
function route(status: () => Promise<Response>, events: () => Promise<Response> = () => json(page([base]))) {
  fetchMock.mockImplementation((url: string) =>
    new URL(String(url)).pathname.endsWith("/world/status") ? status() : events(),
  );
}

describe("LiveEvents category and severity filters", () => {
  it("category chips send the category param and compose with the source filter", async () => {
    route(() => json(statusBody("REPLAY")));
    render(<LiveEvents />);
    await screen.findByText("Strait Test disruption");
    expect(eventCalls()[0]?.searchParams.get("category")).toBeNull();

    const chips = screen.getByRole("group", { name: "Filter events by category" });
    expect(Array.from(chips.querySelectorAll("button")).map((b) => b.textContent)).toEqual([
      "All", "Geopolitics", "Energy", "Supply chain", "Technology", "Macro",
    ]);
    expect(screen.getByRole("button", { name: "All categories" })).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(screen.getByRole("button", { name: "Energy" }));
    await waitFor(() => expect(eventCalls().some((u) => u.searchParams.get("category") === "energy")).toBe(true));
    expect(screen.getByRole("button", { name: "Energy" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Energy" })).toHaveFocus();

    fireEvent.click(screen.getByRole("button", { name: "Supply chain" }));
    await waitFor(() => expect(eventCalls().some((u) => u.searchParams.get("category") === "supply_chain")).toBe(true));

    // Both filters compose: source_type and category in the same request.
    fireEvent.click(screen.getByRole("button", { name: "World" }));
    await waitFor(() =>
      expect(
        eventCalls().some(
          (u) => u.searchParams.get("source_type") === "world" && u.searchParams.get("category") === "supply_chain",
        ),
      ).toBe(true),
    );
    expect(screen.getByRole("button", { name: "World" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Supply chain" })).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(screen.getByRole("button", { name: "All categories" }));
    await waitFor(() => expect(eventCalls().at(-1)?.searchParams.get("category")).toBeNull());
    expect(eventCalls().at(-1)?.searchParams.get("source_type")).toBe("world");
  });

  it("severity select maps Elevated+ / High to severity_min 0.5 / 0.7", async () => {
    route(() => json(statusBody("REPLAY")));
    render(<LiveEvents />);
    await screen.findByText("Strait Test disruption");
    const select = screen.getByRole("combobox", { name: "Minimum severity" });
    expect(select).toHaveValue("any");
    expect(eventCalls()[0]?.searchParams.get("severity_min")).toBeNull();

    fireEvent.change(select, { target: { value: "0.5" } });
    await waitFor(() => expect(eventCalls().some((u) => u.searchParams.get("severity_min") === "0.5")).toBe(true));
    fireEvent.change(screen.getByRole("combobox", { name: "Minimum severity" }), { target: { value: "0.7" } });
    await waitFor(() => expect(eventCalls().some((u) => u.searchParams.get("severity_min") === "0.7")).toBe(true));
    expect(screen.getByRole("combobox", { name: "Minimum severity" })).toHaveValue("0.7");
    expect(screen.getByRole("combobox", { name: "Minimum severity" })).toHaveFocus();

    fireEvent.change(screen.getByRole("combobox", { name: "Minimum severity" }), { target: { value: "any" } });
    await waitFor(() => expect(eventCalls().at(-1)?.searchParams.get("severity_min")).toBeNull());
  });

  it("uses a filter-specific empty state when category or severity narrows the feed", async () => {
    route(() => json(statusBody("REPLAY")), () => json(page([])));
    render(<LiveEvents />);
    await screen.findByText("No events returned");
    fireEvent.click(screen.getByRole("button", { name: "Macro" }));
    expect(await screen.findByText("No events match these filters")).toBeInTheDocument();
  });
});

describe("LiveEvents world mode chip", () => {
  it("shows WORLD REPLAY for a replay feed and never says LIVE", async () => {
    route(() => json(statusBody("REPLAY")));
    render(<LiveEvents />);
    const chip = await screen.findByRole("status", { name: "World feed: replay (not live)" });
    expect(chip).toHaveAttribute("data-mode", "REPLAY");
    expect(chip).toHaveTextContent("WORLD REPLAY");
    expect(chip.textContent).not.toMatch(/live/i);
  });

  it("downgrades a LIVE claim from a replay provider to REPLAY", async () => {
    route(() => json(statusBody("LIVE", "replay")));
    render(<LiveEvents />);
    expect(await screen.findByRole("status", { name: "World feed: replay (not live)" })).toBeInTheDocument();
  });

  it("shows WORLD LIVE only for a live provider", async () => {
    route(() => json(statusBody("LIVE", "world_monitor")));
    render(<LiveEvents />);
    expect(await screen.findByRole("status", { name: "World feed: live" })).toHaveAttribute("data-mode", "LIVE");
  });

  it("shows WORLD OFFLINE when the status request fails", async () => {
    route(() => json({ error: { code: "internal_error", message: "nope" } }, 500));
    render(<LiveEvents />);
    const chip = await screen.findByRole("status", { name: "World feed: offline (no world events)" });
    expect(chip).toHaveTextContent("WORLD OFFLINE");
    // the feed itself is unaffected
    expect(await screen.findByText("Strait Test disruption")).toBeInTheDocument();
  });

  it("shows WORLD OFFLINE when the status payload has no recognised mode", async () => {
    route(() => json({ unexpected: true }));
    render(<LiveEvents />);
    expect(await screen.findByRole("status", { name: "World feed: offline (no world events)" })).toBeInTheDocument();
  });

  it("polls /world/status every 15 s and drops a stale LIVE when a poll fails", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    let n = 0;
    route(() => (n++ === 0 ? json(statusBody("LIVE", "world_monitor")) : json({ error: { code: "x", message: "down" } }, 503)));
    render(<LiveEvents />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(screen.getByRole("status", { name: "World feed: live" })).toBeInTheDocument();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(14_000);
    });
    expect(urls().filter((u) => u.pathname.endsWith("/world/status"))).toHaveLength(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_500);
    });
    expect(urls().filter((u) => u.pathname.endsWith("/world/status"))).toHaveLength(2);
    expect(screen.getByRole("status", { name: "World feed: offline (no world events)" })).toBeInTheDocument();
  });
});
