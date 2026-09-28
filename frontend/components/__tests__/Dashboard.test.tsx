import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { EchoEvent } from "@/types/event";
import type { Bar, MarketStatus, MarketSymbolRow } from "@/types/market";
import { Dashboard } from "../Dashboard";
import { MarketPanel, NO_SHOCKS_MESSAGE, OFFLINE_MESSAGE } from "../market/MarketPanel";

// Test fixtures only (mirror the API contract); mocked fetch, no network.
const SHOCK_AT = "2026-09-21T14:05:00Z";

function status(over: Partial<MarketStatus> = {}): MarketStatus {
  return {
    mode: "REPLAY",
    providers: [
      {
        provider: "replay",
        state: "CONNECTED",
        configured: true,
        mode: "REPLAY",
        last_message_at: "2026-09-21T14:06:00Z",
        last_error: null,
        reconnect_attempts: 0,
        subscribed_symbols: ["NVDA", "AMD", "SOXX"],
        messages_received: 1200,
        malformed_messages: 0,
      },
    ],
    active_provider: "replay",
    subscribed_symbols: ["NVDA", "AMD", "SOXX"],
    last_observation_at: "2026-09-21T14:06:00Z",
    queue: { depth: 0, capacity: 10000, dropped: 0 },
    replay_finished: false,
    session: "REGULAR",
    ...over,
  };
}

function row(over: Partial<MarketSymbolRow>): MarketSymbolRow {
  return {
    symbol: "NVDA",
    group: "Semis",
    role: "equity",
    sector_benchmark: "SOXX",
    price: 118.42,
    change_pct: -4.31,
    as_of: "2026-09-21T14:06:00Z",
    state: "SHOCK",
    shock_score: 0.86,
    volume_z: 6.1,
    return_5m: -0.045,
    sector_residual: -0.041,
    direction: "negative",
    ...over,
  };
}

const ROWS: MarketSymbolRow[] = [
  row({}),
  row({ symbol: "AMD", price: 151.1, change_pct: 0.2, state: "NORMAL", shock_score: 0.1, direction: null }),
  row({ symbol: "SOXX", role: "benchmark", group: "Sector", price: 240.5, change_pct: 0.1, state: "NORMAL", shock_score: null }),
];

function shock(i: number, symbol = "NVDA"): EchoEvent {
  return {
    id: `evt_mkt_${symbol.toLowerCase()}_${i}`,
    timestamp: SHOCK_AT,
    source_type: "market",
    event_type: "market_shock",
    title: `${symbol} abnormal downside move ${i}`,
    summary: null,
    entities: [],
    companies: [symbol],
    locations: [],
    economic_channels: {},
    severity: 0.86,
    novelty: 1,
    corroboration: 0,
    confidence: 0.8,
    source_refs: [{ name: "replay" }],
    metadata: { direction: "negative", shock_score: 0.86, return_5m: -0.045, provider: "replay" },
    is_mock: true,
    created_at: SHOCK_AT,
    ingested_at: SHOCK_AT,
  };
}

function bars(symbol: string, interval: string) {
  const items: Bar[] = Array.from({ length: 12 }, (_, i) => ({
    timestamp: new Date(Date.parse("2026-09-21T13:30:00Z") + i * 5 * 60_000).toISOString(),
    open: 100 + i,
    high: 101 + i,
    low: 99 + i,
    close: 100 + i,
    volume: 1000,
    source: "replay" as const,
  }));
  return { symbol, interval, items };
}

const json = (body: unknown, code = 200) =>
  new Response(JSON.stringify(body), { status: code, headers: { "content-type": "application/json" } });

interface Routes {
  status?: () => Response;
  symbols?: () => Response;
  shocks?: () => Response;
  events?: () => Response;
}

let fetchMock: ReturnType<typeof vi.fn>;

function mockApi(routes: Routes = {}) {
  fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input));
    const p = url.pathname;
    if (p.endsWith("/market/status")) return (routes.status ?? (() => json(status())))();
    if (p.endsWith("/market/symbols")) return (routes.symbols ?? (() => json({ items: ROWS })))();
    if (p.endsWith("/market/shocks")) {
      return (routes.shocks ?? (() => json({ items: [shock(1), shock(2)] })))();
    }
    const m = /\/market\/bars\/([^/]+)$/.exec(p);
    if (m) return json(bars(decodeURIComponent(m[1]!), url.searchParams.get("interval") ?? "5m"));
    if (p.endsWith("/events")) {
      return (routes.events ?? (() => json({ items: [], total: 0, limit: 6, offset: 0 })))();
    }
    return json({ error: { code: "not_found", message: `unmocked ${p}` } }, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
}

const barsCalls = () =>
  fetchMock.mock.calls
    .map((c) => new URL(String(c[0])))
    .filter((u) => u.pathname.includes("/market/bars/"));

beforeEach(() => mockApi());
afterEach(() => vi.unstubAllGlobals());

describe("MarketPanel", () => {
  it("renders feed status, symbols and the latest 5 shocks from the API", async () => {
    mockApi({ shocks: () => json({ items: Array.from({ length: 7 }, (_, i) => shock(i + 1)) }) });
    render(<MarketPanel />);

    const table = await screen.findByRole("region", { name: /Symbols/ });
    expect(within(table).getByText("NVDA")).toBeInTheDocument();
    expect(within(table).getByText("118.42")).toBeInTheDocument();
    expect(within(table).getByText("SOXX")).toBeInTheDocument();

    expect(await screen.findByRole("region", { name: "Feed status" })).toBeInTheDocument();
    expect(screen.getByTestId("provider-replay")).toBeInTheDocument();
    expect(screen.getByRole("status", { name: /Data mode: replay/ })).toBeInTheDocument();

    await waitFor(() => expect(screen.getAllByTestId("shock-card")).toHaveLength(5));
    expect(screen.getByRole("heading", { name: "Detected market shocks" })).toBeInTheDocument();

    // Default selection = first equity, 5m bars, with a marker for its shock.
    await waitFor(() => expect(screen.getAllByTestId("chart-marker").length).toBeGreaterThan(0));
    const first = barsCalls()[0]!;
    expect(first.pathname.endsWith("/market/bars/NVDA")).toBe(true);
    expect(first.searchParams.get("interval")).toBe("5m");
  });

  it("shows the empty shocks state", async () => {
    mockApi({ shocks: () => json({ items: [] }) });
    render(<MarketPanel />);
    expect(await screen.findByText(NO_SHOCKS_MESSAGE)).toBeInTheDocument();
    expect(screen.queryByTestId("shock-card")).not.toBeInTheDocument();
  });

  it("OFFLINE shows the offline empty state and no prices or bar requests", async () => {
    mockApi({
      status: () => json(status({ mode: "OFFLINE", providers: [], active_provider: null, subscribed_symbols: [] })),
      symbols: () => json({ items: ROWS.map((r) => ({ ...r, price: 999.99, state: "NO_DATA" })) }),
      shocks: () => json({ items: [] }),
    });
    render(<MarketPanel />);

    expect(await screen.findByTestId("market-offline")).toHaveTextContent(OFFLINE_MESSAGE);
    expect(OFFLINE_MESSAGE).toBe(
      "Market feed offline — set ECHO_MARKET_PROVIDER=replay to run the replay scenario",
    );
    expect(screen.queryByRole("region", { name: /Symbols/ })).not.toBeInTheDocument();
    expect(screen.queryByTestId("price-chart")).not.toBeInTheDocument();
    expect(screen.queryByText("999.99")).not.toBeInTheDocument();
    expect(screen.getByRole("status", { name: /Data mode: offline/ })).toBeInTheDocument();
    expect(barsCalls()).toHaveLength(0);
  });

  it("shows an error state when the symbols request fails, without fake data", async () => {
    mockApi({
      symbols: () => json({ error: { code: "internal_error", message: "boom", request_id: "r1" } }, 500),
    });
    render(<MarketPanel />);

    expect(await screen.findByText("Could not load market symbols")).toBeInTheDocument();
    expect(screen.getByText("boom")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: /Symbols/ })).not.toBeInTheDocument();
  });

  it("shows a loading state before the first response", () => {
    fetchMock = vi.fn(() => new Promise<Response>(() => {}));
    vi.stubGlobal("fetch", fetchMock);
    render(<MarketPanel />);
    expect(screen.getAllByTestId("market-loading").length).toBeGreaterThan(0);
    expect(screen.queryByRole("region", { name: /Symbols/ })).not.toBeInTheDocument();
  });

  it("selecting a symbol requests its bars; changing interval refetches", async () => {
    render(<MarketPanel />);
    await waitFor(() => expect(barsCalls().length).toBeGreaterThan(0));
    expect(screen.getByTestId("chart-quote")).toHaveTextContent("NVDA");

    const amd = (await screen.findByRole("region", { name: /Symbols/ })).querySelector('tr[data-symbol="AMD"]')!;
    fireEvent.click(amd);

    await waitFor(() =>
      expect(barsCalls().some((u) => u.pathname.endsWith("/market/bars/AMD") && u.searchParams.get("interval") === "5m")).toBe(true),
    );
    await waitFor(() => expect(screen.getByTestId("chart-quote")).toHaveTextContent("AMD"));
    // Only NVDA's shock exists, so AMD's chart carries no marker.
    await waitFor(() => expect(screen.getByTestId("price-line")).toBeInTheDocument());
    expect(screen.queryByTestId("chart-marker")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("radio", { name: "15m" }));
    await waitFor(() =>
      expect(barsCalls().some((u) => u.pathname.endsWith("/market/bars/AMD") && u.searchParams.get("interval") === "15m")).toBe(true),
    );
  });

  it("reports a summary (mode + shock count) to its parent", async () => {
    const onSummary = vi.fn();
    render(<MarketPanel onSummary={onSummary} />);
    await waitFor(() =>
      expect(onSummary).toHaveBeenLastCalledWith({ mode: "REPLAY", shocks: 2, failed: false }),
    );
  });
});

describe("Dashboard", () => {
  it("keeps the world-event summary and adds the Market region", async () => {
    const event = { ...shock(1), source_type: "world", event_type: "port_closure", title: "Port closure test event", companies: ["XOM"] } as EchoEvent;
    mockApi({ events: () => json({ items: [event], total: 1, limit: 6, offset: 0 }) });
    render(<Dashboard />);

    expect(screen.getByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
    expect((await screen.findAllByText("Port closure test event")).length).toBeGreaterThan(0);
    expect(screen.getByRole("heading", { name: "Live events" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Global shock map" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Highest opportunity" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Prediction performance" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Prediction vs reality" })).toBeInTheDocument();

    const market = screen.getByTestId("market-panel");
    expect(await within(market).findByRole("region", { name: /Symbols/ })).toBeInTheDocument();
    expect(await within(market).findAllByTestId("shock-card")).toHaveLength(2);

    // The metric card reflects the real shock count instead of a placeholder.
    const metric = screen.getByText("Market shocks", { selector: ".label" }).closest("article")!;
    await waitFor(() => expect(within(metric).getByText("2")).toBeInTheDocument());
  });

  it("still renders the Market region when the events feed fails", async () => {
    mockApi({ events: () => json({ error: { code: "internal_error", message: "events down" } }, 500) });
    render(<Dashboard />);
    expect(await screen.findByText("Live event feed unavailable")).toBeInTheDocument();
    const market = screen.getByTestId("market-panel");
    expect(await within(market).findByRole("region", { name: /Symbols/ })).toBeInTheDocument();
  });
});
