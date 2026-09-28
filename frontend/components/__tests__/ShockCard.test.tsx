import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { EchoEvent } from "@/types/event";
import { ShockCard } from "../market/ShockCard";

// Test fixture only (mirrors backend shock/events.py metadata keys).
const base: EchoEvent = {
  id: "evt_mkt_nvda_202609201530_neg",
  timestamp: "2026-09-20T15:30:00Z",
  source_type: "market",
  event_type: "market_shock",
  title: "NVDA abnormal downside move",
  summary: "NVDA shock",
  entities: [],
  companies: ["NVDA"],
  locations: [],
  economic_channels: {},
  severity: 0.86,
  novelty: 1,
  corroboration: 0,
  confidence: 0.33,
  source_refs: [{ name: "massive" }],
  metadata: {
    direction: "negative",
    level: "SHOCK",
    shock_score: 0.86,
    calibrated: false,
    return_5m: -0.045,
    return_z: -5.23,
    volume_z: 7.81,
    volatility_z: 4.4,
    sector_residual: -0.0431,
    market_residual: -0.0442,
    sector_benchmark: "SOXX",
    provider: "massive",
  },
  is_mock: false,
  created_at: "2026-09-20T15:30:00Z",
  ingested_at: "2026-09-20T15:30:01Z",
};

const m = (label: string) => screen.getByTestId(`metric-${label}`);

describe("ShockCard", () => {
  it("renders badge, symbol, title, direction, score and all metrics", () => {
    render(<ShockCard event={base} />);
    expect(screen.getByText("MARKET SHOCK")).toBeInTheDocument();
    expect(screen.getByText("NVDA")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: base.title })).toBeInTheDocument();
    expect(screen.getByText("▼")).toBeInTheDocument();
    expect(screen.getByTestId("shock-score")).toHaveTextContent("Shock score 0.86");
    expect(m("5m return")).toHaveTextContent("-4.50%");
    expect(m("Return")).toHaveTextContent("-5.2σ");
    expect(m("Volume")).toHaveTextContent("+7.8σ");
    expect(m("Volatility")).toHaveTextContent("+4.4σ");
    expect(m("Sector resid.")).toHaveTextContent("-4.31%");
    expect(m("Market resid.")).toHaveTextContent("-4.42%");
    expect(m("Sector bench.")).toHaveTextContent("SOXX");
    expect(m("Provider")).toHaveTextContent("massive");
    expect(screen.getByText("2026-09-20 15:30:00 UTC")).toBeInTheDocument();
    expect(screen.queryByText(/REPLAY/)).not.toBeInTheDocument();
  });

  it("shows upside as green up arrow", () => {
    render(<ShockCard event={{ ...base, metadata: { ...base.metadata, direction: "positive" } }} />);
    expect(screen.getByText("▲")).toBeInTheDocument();
  });

  it("shows a dash for missing / NaN / null / non-numeric metadata", () => {
    const metadata = {
      shock_score: Number.NaN,
      return_5m: null,
      return_z: Number.POSITIVE_INFINITY,
      volume_z: "high",
      sector_benchmark: "",
    };
    render(<ShockCard event={{ ...base, metadata }} />);
    expect(screen.getByTestId("shock-score")).toHaveTextContent("Shock score —");
    for (const label of [
      "5m return",
      "Return",
      "Volume",
      "Volatility",
      "Sector resid.",
      "Market resid.",
      "Sector bench.",
      "Provider",
    ]) {
      expect(m(label)).toHaveTextContent("—");
    }
    expect(screen.getByText("—", { selector: "[data-testid=shock-direction]" })).toBeInTheDocument();
  });

  it("does not crash on empty metadata and no companies", () => {
    render(<ShockCard event={{ ...base, metadata: {}, companies: [] }} />);
    expect(screen.getByTestId("shock-card")).toBeInTheDocument();
  });

  it("shows the REPLAY / MOCK badge when is_mock", () => {
    render(<ShockCard event={{ ...base, is_mock: true }} />);
    expect(screen.getByText("REPLAY / MOCK")).toBeInTheDocument();
  });

  it("never shows a percent-confidence and labels the score as heuristic", () => {
    const { container } = render(<ShockCard event={base} />);
    expect(container.textContent).not.toMatch(/86\s*%|confidence/i);
    expect(container.textContent).not.toMatch(/0\.33|33\s*%/); // event.confidence is not rendered
    const score = screen.getByTestId("shock-score");
    expect(score).toHaveAttribute("title", "heuristic score, not a calibrated probability");
    expect(score).toHaveAccessibleDescription("heuristic score, not a calibrated probability");
  });
});
