import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { EchoEvent } from "@/types/event";
import { EventDetailView } from "../EventDetailView";

const world: EchoEvent = {
  id: "evt_world_hormuz",
  timestamp: "2026-09-16T09:00:00Z",
  source_type: "world",
  event_type: "shipping_disruption",
  title: "Tanker traffic halts in Strait of Hormuz",
  summary: "Multiple tankers reported holding position outside the strait.",
  entities: ["Strait of Hormuz", "crude oil"],
  companies: [],
  locations: ["Strait of Hormuz", "Iran"],
  economic_channels: { oil_supply: -0.82, shipping_costs: 0.77, energy_prices: 0.73 },
  severity: 0.82,
  novelty: 0.64,
  corroboration: 0.71,
  confidence: 0.66,
  source_refs: [{ provider: "replay" }],
  metadata: {
    channel_evidence: {
      oil_supply: ["class:shipping_disruption", "entity:Strait of Hormuz"],
      shipping_costs: "not-a-list",
    },
  },
  is_mock: false,
  created_at: "2026-09-16T09:00:00Z",
  ingested_at: "2026-09-16T09:00:05Z",
  revision: 2,
  updated_at: "2026-09-16T09:40:00Z",
  source_count: 3,
  independent_source_count: 2,
};

const src = (over: Record<string, unknown> = {}) => ({
  provider: "replay",
  source_name: "Fixture Wire",
  source_group: "fixturewire",
  source_url: "https://example.com/hormuz",
  headline: "Tankers hold outside Hormuz",
  published_at: "2026-09-16T09:05:00Z",
  retrieved_at: "2026-09-16T09:06:00Z",
  is_independent: true,
  syndicated_from: null,
  reliability: 0.8,
  ...over,
});

const json = (body: unknown, status = 200) =>
  Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }));

let fetchMock: ReturnType<typeof vi.fn>;
const route = (event: EchoEvent, sources: () => Promise<Response>) =>
  fetchMock.mockImplementation((url: string) => {
    const path = new URL(String(url)).pathname;
    return path.endsWith("/sources") ? sources() : json(event);
  });

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  vi.unstubAllGlobals();
});

describe("EventDetailView world event", () => {
  it("renders scores, entities, channels with evidence, sources panel, timeline and semantics", async () => {
    route(world, () =>
      json({
        items: [src(), src({ source_name: "Repub Daily", source_group: "repub", is_independent: false, syndicated_from: "fixturewire", source_url: "javascript:alert(1)" })],
        total: 2,
      }),
    );
    render(<EventDetailView id={world.id} />);

    expect(await screen.findByRole("heading", { name: world.title })).toBeInTheDocument();
    expect(screen.getByTestId("world-summary")).toHaveTextContent("Multiple tankers reported");

    // scores: bucket + 0.00 numbers, corroboration wording, confidence tooltip, no percentages
    expect(screen.getByTestId("severity-bucket")).toHaveTextContent("HIGH");
    expect(screen.getByRole("meter", { name: "Severity" })).toHaveAttribute("aria-valuetext", "HIGH 0.82");
    expect(screen.getByText("Novelty")).toBeInTheDocument();
    expect(screen.getByTestId("corroboration-line")).toHaveTextContent(
      "Corroboration: 2 independent sources (score 0.71)",
    );
    expect(screen.getByText("Confidence score")).toHaveAttribute(
      "title",
      expect.stringMatching(/not a calibrated probability/i),
    );

    // locations + entities chips
    expect(screen.getByRole("list", { name: "Locations" })).toHaveTextContent("Iran");
    expect(screen.getByRole("list", { name: "Entities" })).toHaveTextContent("crude oil");

    // channels + evidence (only well-formed rule lists), legend
    const channels = screen.getByRole("list", { name: "Economic channels" });
    expect(within(channels).getAllByTestId("channel-row")).toHaveLength(3);
    expect(screen.getByText(/not an expected price move/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Evidence for Oil supply" }));
    expect(screen.getByText("entity:Strait of Hormuz")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Evidence for Shipping costs" })).not.toBeInTheDocument();

    // sources panel (fed by /events/{id}/sources) + timeline
    const panel = await screen.findByTestId("source-evidence");
    expect(within(panel).getAllByTestId("source-item")).toHaveLength(2);
    expect(within(panel).getByTestId("source-summary")).toHaveTextContent("2 sources · 1 independent");
    expect(within(panel).getByRole("link", { name: "Tankers hold outside Hormuz" })).toHaveAttribute("rel", "noopener noreferrer");
    expect(within(panel).getByTestId("source-url-text")).toHaveTextContent("javascript:alert(1)");
    expect(screen.getByRole("list", { name: "Event timeline" })).toHaveTextContent("Fixture Wire");
    expect(screen.getByRole("list", { name: "Event timeline" })).toHaveTextContent("revision 2");
    expect(fetchMock.mock.calls.some((c) => String(c[0]).includes(`/events/${world.id}/sources`))).toBe(true);

    // semantics
    const sem = screen.getByTestId("score-semantics");
    expect(within(sem).getByText("Score semantics")).toBeInTheDocument();
    expect(sem).toHaveTextContent(/economic significance if the event is true/i);
    expect(sem).toHaveTextContent(/not sentiment/i);
    expect(sem).toHaveTextContent(/independent sources/i);
    expect(sem).toHaveTextContent(/not a calibrated probability/i);
    expect(sem).toHaveTextContent(/directional pressure/i);

    // hard rules
    expect(screen.queryByTestId("shock-metrics")).not.toBeInTheDocument();
    const text = document.body.textContent ?? "";
    expect(text).not.toMatch(/\d\s*%/);
    expect(text).not.toMatch(/\b(buy|sell|recommend)/i);
  });

  it("marks replay sources with a REPLAY chip", async () => {
    route(world, () => json({ items: [src()], total: 1 }));
    render(<EventDetailView id={world.id} />);
    const panel = await screen.findByTestId("source-evidence");
    expect(within(panel).getByText("REPLAY")).toBeInTheDocument();
  });

  it("shows a loading state for sources, then the error state with retry", async () => {
    let fail = true;
    let release: (() => void) | null = null;
    route(world, () =>
      fail
        ? new Promise<Response>((resolve) => {
            release = () => resolve(new Response(JSON.stringify({ error: { code: "internal_error", message: "sources down" } }), { status: 500 }));
          })
        : json({ items: [src()], total: 1 }),
    );
    render(<EventDetailView id={world.id} />);
    expect(await screen.findByTestId("source-evidence-loading")).toBeInTheDocument();
    // the rest of the event is usable while sources load
    expect(screen.getByTestId("world-detail")).toBeInTheDocument();

    release!();
    expect(await screen.findByText("Could not load source evidence")).toBeInTheDocument();
    expect(screen.getByText("sources down")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: world.title })).toBeInTheDocument();

    fail = false;
    fireEvent.click(screen.getByRole("button", { name: "Retry sources" }));
    expect(await screen.findByTestId("source-evidence")).toBeInTheDocument();
  });

  it("shows the empty state when no sources are recorded", async () => {
    route(world, () => json({ items: [], total: 0 }));
    render(<EventDetailView id={world.id} />);
    expect(await screen.findByTestId("source-evidence-empty")).toHaveTextContent("No source evidence recorded");
    expect(screen.getByRole("list", { name: "Event timeline" })).toBeInTheDocument();
  });

  it("does not invent channel evidence or independent counts when absent", async () => {
    const bare = { ...world, metadata: {}, economic_channels: {}, independent_source_count: undefined, source_count: undefined };
    route(bare as EchoEvent, () => json({ items: [], total: 0 }));
    render(<EventDetailView id={world.id} />);
    expect(await screen.findByText("No economic channels identified")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Evidence for/ })).not.toBeInTheDocument();
    expect(await screen.findByTestId("corroboration-line")).toHaveTextContent(
      "Corroboration: independent source count unavailable (score 0.71)",
    );
  });
});

describe("EventDetailView market shock (unchanged)", () => {
  it("keeps the shock metrics table and makes no sources request", async () => {
    const shock: EchoEvent = {
      ...world,
      id: "evt_mkt_nvda_1",
      source_type: "market",
      event_type: "market_shock",
      title: "NVDA abnormal downside move",
      economic_channels: {},
      metadata: { direction: "negative", shock_score: 0.864, provider: "replay" },
    };
    fetchMock.mockImplementation(() => json(shock));
    render(<EventDetailView id={shock.id} />);
    expect(await screen.findByTestId("shock-metrics")).toHaveTextContent("0.864");
    expect(screen.queryByTestId("world-detail")).not.toBeInTheDocument();
    expect(screen.queryByTestId("score-semantics")).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.every((c) => !String(c[0]).endsWith("/sources"))).toBe(true);
  });
});
