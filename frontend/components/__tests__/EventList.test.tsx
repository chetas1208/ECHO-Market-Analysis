import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { EchoEvent } from "@/types/event";
import { EventCard } from "../EventCard";
import { EventList } from "../EventList";

// Test fixture only (mirrors the API contract); the app itself contains no hardcoded events.
const NOW = Date.parse("2026-09-20T12:00:00Z");
const event: EchoEvent = {
  id: "evt_test_001",
  timestamp: "2026-09-20T09:00:00Z",
  source_type: "world",
  event_type: "geopolitical_shipping_disruption",
  title: "Strait Test — Increased Naval Activity",
  summary: "Synthetic summary for tests.",
  entities: ["Test Navy"],
  companies: ["XOM"],
  locations: ["Strait Test"],
  economic_channels: { oil_supply: -0.82, shipping_costs: 0.77 },
  severity: 0.88,
  novelty: 0.5,
  corroboration: 0.6,
  confidence: 0.91,
  source_refs: [],
  metadata: {},
  is_mock: true,
  created_at: "2026-09-20T09:00:00Z",
  ingested_at: "2026-09-20T09:00:01Z",
};

describe("EventCard", () => {
  it("renders title, timestamps, scores, signed channels and the mock badge", () => {
    render(<EventCard event={event} now={NOW} />);

    expect(screen.getByRole("heading", { name: event.title })).toBeInTheDocument();
    expect(screen.getByText("MOCK / FIXTURE")).toBeInTheDocument();
    expect(screen.getByText("world")).toBeInTheDocument();
    expect(screen.getByTestId("event-type")).toHaveTextContent("geopolitical_shipping_disruption");
    expect(screen.getByText("2026-09-20 09:00:00 UTC")).toBeInTheDocument();
    expect(screen.getByText(/3h ago/)).toBeInTheDocument();

    const severity = screen.getByRole("meter", { name: "Severity" });
    expect(severity).toHaveAttribute("aria-valuenow", "0.88");
    expect(screen.getByRole("meter", { name: "Confidence" })).toHaveAttribute("aria-valuenow", "0.91");

    const channels = within(screen.getByRole("list", { name: "Economic channels" }));
    expect(channels.getByText("-0.82")).toHaveClass("channels__value--neg");
    expect(channels.getByText("+0.77")).toHaveClass("channels__value--pos");
    // Sorted by magnitude: oil supply (0.82) before shipping costs (0.77).
    const rows = channels.getAllByRole("listitem");
    expect(rows[0]).toHaveTextContent("oil supply");
    expect(rows[1]).toHaveTextContent("shipping costs");
  });

  it("omits the mock badge for real events", () => {
    render(<EventCard event={{ ...event, is_mock: false }} now={NOW} />);
    expect(screen.queryByText("MOCK / FIXTURE")).not.toBeInTheDocument();
  });
});

describe("EventList states", () => {
  it("shows a loading state", () => {
    render(<EventList status="loading" />);
    expect(screen.getByRole("status")).toHaveAttribute("aria-busy", "true");
  });

  it("shows the empty state pointing at make seed", () => {
    render(<EventList status="success" events={[]} />);
    expect(screen.getByText("No events yet")).toBeInTheDocument();
    expect(screen.getByText("make seed")).toBeInTheDocument();
  });

  it("shows the error envelope message + request id and retries", () => {
    const onRetry = vi.fn();
    render(
      <EventList
        status="error"
        error={{ message: "Database is unavailable", code: "database_error", requestId: "req_abc123", status: 500 }}
        onRetry={onRetry}
      />,
    );
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Database is unavailable");
    expect(alert).toHaveTextContent("req_abc123");
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("renders one card per event", () => {
    render(<EventList status="success" events={[event, { ...event, id: "evt_test_002", title: "Second" }]} now={NOW} />);
    expect(screen.getAllByRole("article")).toHaveLength(2);
  });
});
