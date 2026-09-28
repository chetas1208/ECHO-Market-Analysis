import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { EchoEvent } from "@/types/event";
import { EventCard } from "../EventCard";
import { severityBucket } from "../ScoreRow";

const NOW = Date.parse("2026-09-20T12:00:00Z");
const world: EchoEvent = {
  id: "evt_world_hormuz",
  timestamp: "2026-09-20T09:00:00Z",
  source_type: "world",
  event_type: "shipping_disruption",
  title: "Tanker traffic halted in Strait of Hormuz",
  summary: null,
  entities: ["Strait of Hormuz"],
  companies: [],
  locations: ["Strait of Hormuz", "Gulf of Oman"],
  economic_channels: { oil_supply: -0.8 },
  severity: 0.82,
  novelty: 0.4,
  corroboration: 0.67,
  confidence: 0.55,
  source_refs: [],
  metadata: {},
  is_mock: false,
  created_at: "2026-09-20T09:00:00Z",
  ingested_at: "2026-09-20T09:00:01Z",
};
type WithCounts = EchoEvent & { source_count?: number; independent_source_count?: number };

function scores() {
  return within(screen.getByTestId("world-scores"));
}

describe("severityBucket", () => {
  it("uses the documented thresholds", () => {
    expect(severityBucket(0.7)).toBe("HIGH");
    expect(severityBucket(0.69)).toBe("ELEVATED");
    expect(severityBucket(0.5)).toBe("ELEVATED");
    expect(severityBucket(0.49)).toBe("MODERATE");
    expect(severityBucket(0.3)).toBe("MODERATE");
    expect(severityBucket(0.29)).toBe("LOW");
    expect(severityBucket(0)).toBe("LOW");
  });
});

describe("EventCard world scores", () => {
  it("shows severity bucket, numeric score and non-percentage labels", () => {
    render(<EventCard event={world} now={NOW} />);

    expect(screen.getByTestId("severity-bucket")).toHaveTextContent("HIGH");
    const region = screen.getByTestId("world-scores");
    expect(region).toHaveTextContent("Severity");
    expect(region).toHaveTextContent("0.82");
    expect(region).toHaveTextContent("Novelty");
    expect(region).toHaveTextContent("0.40");
    expect(region).toHaveTextContent("Confidence score");
    expect(region).toHaveTextContent("0.55");
    expect(region).toHaveTextContent("Corroboration");
    expect(region.textContent).not.toContain("%");
    expect(screen.getByRole("meter", { name: "Severity" })).toHaveAttribute("aria-valuenow", "0.82");
    expect(screen.getByRole("meter", { name: "Confidence" })).toHaveAttribute("aria-valuenow", "0.55");
  });

  it("buckets lower severities", () => {
    const { rerender } = render(<EventCard event={{ ...world, severity: 0.55 }} now={NOW} />);
    expect(screen.getByTestId("severity-bucket")).toHaveTextContent("ELEVATED");
    rerender(<EventCard event={{ ...world, severity: 0.35 }} now={NOW} />);
    expect(screen.getByTestId("severity-bucket")).toHaveTextContent("MODERATE");
    rerender(<EventCard event={{ ...world, severity: 0.1 }} now={NOW} />);
    expect(screen.getByTestId("severity-bucket")).toHaveTextContent("LOW");
  });

  it("explains that confidence is a heuristic, not a probability", () => {
    render(<EventCard event={world} now={NOW} />);
    const tip = "Heuristic interpretation confidence — not a calibrated probability";
    expect(screen.getAllByTitle(tip).length).toBeGreaterThan(0);
    expect(scores().getByText("Confidence score")).toHaveAttribute("title", tip);
  });

  it("falls back to the corroboration score when independent_source_count is absent", () => {
    render(<EventCard event={world} now={NOW} />);
    expect(screen.getByTestId("corroboration")).toHaveTextContent("score 0.67");
    expect(screen.getByTestId("corroboration")).not.toHaveTextContent("independent");
  });

  it("shows independent source wording (singular and plural)", () => {
    const { rerender } = render(
      <EventCard event={{ ...world, independent_source_count: 3, source_count: 5 } as WithCounts} now={NOW} />,
    );
    expect(screen.getByTestId("corroboration")).toHaveTextContent("3 independent sources");
    expect(screen.getByTestId("corroboration")).not.toHaveTextContent("score");
    rerender(<EventCard event={{ ...world, independent_source_count: 1 } as WithCounts} now={NOW} />);
    expect(screen.getByTestId("corroboration")).toHaveTextContent(/^Corroboration1 independent source$/);
    expect(screen.getByTestId("world-scores").textContent).not.toContain("%");
  });

  it("shows the first location and source count when present", () => {
    render(<EventCard event={{ ...world, source_count: 4 } as WithCounts} now={NOW} />);
    expect(screen.getByTestId("world-location")).toHaveTextContent("Strait of Hormuz");
    expect(screen.getByTestId("world-location")).not.toHaveTextContent("Gulf of Oman");
    expect(screen.getByTestId("world-source-count")).toHaveTextContent("4 sources");
  });

  it("omits the meta line when there is no location or source count", () => {
    render(<EventCard event={{ ...world, locations: [] }} now={NOW} />);
    expect(screen.queryByTestId("world-meta")).not.toBeInTheDocument();
  });

  it("leaves market shock rendering unchanged (shock score, no confidence meter, no world scores)", () => {
    const shock: EchoEvent = {
      ...world,
      id: "evt_mkt_nvda",
      source_type: "market",
      event_type: "market_shock",
      locations: [],
      economic_channels: {},
      metadata: { direction: "negative", shock_score: 0.864 },
    };
    render(<EventCard event={shock} now={NOW} />);
    expect(screen.getByTestId("shock-score")).toHaveTextContent("Shock score 0.86");
    expect(screen.queryByRole("meter", { name: "Confidence" })).not.toBeInTheDocument();
    expect(screen.queryByTestId("world-scores")).not.toBeInTheDocument();
  });
});
