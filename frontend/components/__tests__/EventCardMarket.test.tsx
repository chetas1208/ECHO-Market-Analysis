import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { EchoEvent } from "@/types/event";
import { EventCard } from "../EventCard";

const NOW = Date.parse("2026-09-20T12:00:00Z");
const base: EchoEvent = {
  id: "evt_mkt_nvda_202609201500_neg",
  timestamp: "2026-09-20T09:00:00Z",
  source_type: "market",
  event_type: "market_shock",
  title: "NVDA abnormal downside move",
  summary: "NVDA fell 4.5% in 5 bars on 8x volume.",
  entities: [],
  companies: ["NVDA"],
  locations: [],
  economic_channels: {},
  severity: 0.86,
  novelty: 1,
  corroboration: 0,
  confidence: 0.8,
  source_refs: [{ name: "replay" }],
  metadata: { direction: "negative", shock_score: 0.864, calibrated: false },
  is_mock: false,
  created_at: "2026-09-20T09:00:00Z",
  ingested_at: "2026-09-20T09:00:01Z",
};

describe("EventCard market shock", () => {
  it("shows MARKET SHOCK badge, down arrow, ticker chip and shock score instead of confidence", () => {
    render(<EventCard event={base} now={NOW} />);

    expect(screen.getByText("MARKET SHOCK")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Downside move" })).toHaveTextContent("▼");
    const tickers = screen.getByRole("list", { name: "Tickers" });
    expect(tickers).toHaveTextContent("NVDA");
    expect(screen.getByTestId("shock-score")).toHaveTextContent("Shock score 0.86");
    expect(screen.getByRole("meter", { name: "Shock score" })).toHaveAttribute("aria-valuenow", "0.864");
    expect(screen.queryByRole("meter", { name: "Confidence" })).not.toBeInTheDocument();
    expect(screen.getByTestId("shock-score")).not.toHaveTextContent("%");
    expect(screen.getByTestId("event-type")).toHaveTextContent("market_shock");
  });

  it("shows an up arrow for positive direction", () => {
    render(<EventCard event={{ ...base, metadata: { direction: "positive", shock_score: 0.7 } }} now={NOW} />);
    expect(screen.getByRole("img", { name: "Upside move" })).toHaveTextContent("▲");
  });

  it("hides the empty economic channels section for shocks", () => {
    render(<EventCard event={base} now={NOW} />);
    expect(screen.queryByText("Economic channels")).not.toBeInTheDocument();
    expect(screen.queryByText("No economic channels mapped.")).not.toBeInTheDocument();
  });

  it("degrades gracefully when shock_score is missing", () => {
    render(<EventCard event={{ ...base, metadata: {} }} now={NOW} />);
    expect(screen.getByTestId("shock-score")).toHaveTextContent("Shock score —");
    expect(screen.getByRole("img", { name: "Direction unknown" })).toBeInTheDocument();
  });

  it("keeps the mock badge on mock shocks (replay)", () => {
    render(<EventCard event={{ ...base, is_mock: true }} now={NOW} />);
    expect(screen.getByText("MOCK / FIXTURE")).toBeInTheDocument();
    expect(screen.getByText("MARKET SHOCK")).toBeInTheDocument();
  });

  it("leaves world events unchanged: source badge, confidence meter, channels", () => {
    const world: EchoEvent = {
      ...base,
      id: "evt_w",
      source_type: "world",
      event_type: "geopolitical_shipping_disruption",
      title: "Strait Test",
      economic_channels: { oil_supply: -0.82 },
      metadata: {},
      companies: ["XOM"],
    };
    render(<EventCard event={world} now={NOW} />);
    expect(screen.getByText("world")).toBeInTheDocument();
    expect(screen.queryByText("MARKET SHOCK")).not.toBeInTheDocument();
    expect(screen.getByRole("meter", { name: "Confidence" })).toBeInTheDocument();
    expect(screen.queryByRole("meter", { name: "Shock score" })).not.toBeInTheDocument();
    expect(screen.queryByTestId("shock-line")).not.toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Economic channels" })).toHaveTextContent("oil supply");
  });

  it("labels non-shock market and financial events with their source", () => {
    const { rerender } = render(<EventCard event={{ ...base, event_type: "volume_spike" }} now={NOW} />);
    expect(screen.getByText("market")).toBeInTheDocument();
    expect(screen.queryByText("MARKET SHOCK")).not.toBeInTheDocument();
    expect(screen.getByRole("meter", { name: "Confidence" })).toBeInTheDocument();
    rerender(<EventCard event={{ ...base, source_type: "financial", event_type: "earnings" }} now={NOW} />);
    expect(screen.getByText("financial")).toBeInTheDocument();
  });
});
