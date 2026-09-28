import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { MarketStatus, ProviderHealth } from "@/types/market";
import { FeedStatus } from "../market/FeedStatus";

// Test fixtures only (mirror the API contract).
const NOW = Date.parse("2026-09-21T14:30:15.000Z");

function provider(over: Partial<ProviderHealth>): ProviderHealth {
  return {
    provider: "massive",
    state: "CONNECTED",
    configured: true,
    mode: "LIVE",
    last_message_at: "2026-09-21T14:30:12.045Z",
    last_error: null,
    reconnect_attempts: 0,
    subscribed_symbols: ["NVDA", "SOXX", "SPY"],
    messages_received: 1234,
    malformed_messages: 0,
    ...over,
  };
}

function status(over: Partial<MarketStatus> = {}): MarketStatus {
  return {
    mode: "LIVE",
    providers: [provider({})],
    active_provider: "massive",
    subscribed_symbols: ["NVDA", "SOXX", "SPY"],
    last_observation_at: "2026-09-21T14:30:12.045Z",
    queue: { depth: 3, capacity: 1000, dropped: 0 },
    replay_finished: false,
    session: "REGULAR",
    ...over,
  };
}

const chip = (id: string) =>
  within(screen.getByTestId(`provider-${id}`)).getByTestId("state-chip");

describe("FeedStatus", () => {
  it("renders a provider row with UTC ms timestamp, age, counts, queue and session", () => {
    render(<FeedStatus status={status()} loading={false} error={null} now={NOW} />);
    const row = screen.getByTestId("provider-massive");
    expect(chip("massive")).toHaveTextContent("CONNECTED");
    expect(row).toHaveTextContent("14:30:12.045 UTC");
    expect(row).toHaveTextContent("2s ago");
    expect(row).toHaveTextContent("msgs 1,234");
    expect(row).toHaveTextContent("malformed 0");
    expect(row).toHaveTextContent("reconnects 0");
    expect(row).toHaveTextContent("symbols 3");
    expect(screen.getByTestId("feed-queue")).toHaveTextContent("queue 3/1,000 dropped 0");
    expect(screen.getByTestId("feed-session")).toHaveTextContent("REGULAR");
    expect(screen.queryByText("STANDBY")).not.toBeInTheDocument();
    expect(screen.queryByTestId("replay-finished")).not.toBeInTheDocument();
  });

  it("shows a STANDBY label for a configured fallback that is not active", () => {
    render(
      <FeedStatus
        now={NOW}
        loading={false}
        error={null}
        status={status({
          providers: [
            provider({}),
            provider({ provider: "alpaca", state: "DISCONNECTED", last_message_at: null }),
          ],
        })}
      />,
    );
    expect(within(screen.getByTestId("provider-alpaca")).getByText("STANDBY")).toBeInTheDocument();
    expect(within(screen.getByTestId("provider-massive")).queryByText("STANDBY")).toBeNull();
    expect(within(screen.getByTestId("provider-alpaca")).getByText("no messages yet")).toBeInTheDocument();
  });

  it("renders every state chip with its state text and a state attribute", () => {
    const states = ["CONNECTED", "DEGRADED", "RECONNECTING", "STALE", "DISCONNECTED"] as const;
    render(
      <FeedStatus
        now={NOW}
        loading={false}
        error={null}
        status={status({
          active_provider: null,
          providers: states.map((s, i) => provider({ provider: `p${i}` as never, state: s })),
        })}
      />,
    );
    states.forEach((s, i) => {
      expect(chip(`p${i}`)).toHaveTextContent(s);
      expect(screen.getByTestId(`provider-p${i}`)).toHaveAttribute("data-state", s);
    });
  });

  it("shows a stale provider with its last message age, reconnects and error", () => {
    render(
      <FeedStatus
        now={NOW}
        loading={false}
        error={null}
        status={status({
          providers: [
            provider({
              state: "STALE",
              last_message_at: "2026-09-21T14:25:10.500Z",
              reconnect_attempts: 4,
              malformed_messages: 7,
              last_error: "no messages for 300s",
            }),
          ],
        })}
      />,
    );
    const row = screen.getByTestId("provider-massive");
    expect(chip("massive")).toHaveTextContent("STALE");
    expect(row).toHaveTextContent("14:25:10.500 UTC");
    expect(row).toHaveTextContent("5m 04s ago");
    expect(row).toHaveTextContent("reconnects 4");
    expect(row).toHaveTextContent("malformed 7");
    expect(row).toHaveTextContent("no messages for 300s");
  });

  it("renders an unconfigured provider without STANDBY or a timestamp", () => {
    render(
      <FeedStatus
        now={NOW}
        loading={false}
        error={null}
        status={status({
          mode: "OFFLINE",
          active_provider: null,
          subscribed_symbols: [],
          last_observation_at: null,
          providers: [
            provider({
              provider: "alpaca",
              state: "UNCONFIGURED",
              configured: false,
              last_message_at: null,
              subscribed_symbols: [],
              messages_received: 0,
            }),
          ],
        })}
      />,
    );
    expect(chip("alpaca")).toHaveTextContent("UNCONFIGURED");
    expect(screen.queryByText("STANDBY")).not.toBeInTheDocument();
    expect(screen.getByText("no messages yet")).toBeInTheDocument();
  });

  it("notes when replay has finished", () => {
    render(
      <FeedStatus
        now={NOW}
        loading={false}
        error={null}
        status={status({
          mode: "REPLAY",
          replay_finished: true,
          session: "CLOSED",
          providers: [provider({ provider: "replay", mode: "REPLAY" })],
          active_provider: "replay",
        })}
      />,
    );
    expect(screen.getByTestId("replay-finished")).toBeInTheDocument();
    expect(screen.getByTestId("feed-session")).toHaveTextContent("CLOSED");
  });

  it("shows the OFFLINE empty state when no providers exist or status is null", () => {
    const { rerender } = render(
      <FeedStatus loading={false} error={null} status={status({ mode: "OFFLINE", providers: [], active_provider: null })} />,
    );
    const msg = "No market provider configured — set ECHO_MARKET_PROVIDER";
    expect(screen.getByTestId("feed-offline")).toHaveTextContent(msg);
    rerender(<FeedStatus status={null} loading={false} error={null} />);
    expect(screen.getByTestId("feed-offline")).toHaveTextContent(msg);
  });

  it("shows a loading skeleton while loading without data", () => {
    render(<FeedStatus status={null} loading error={null} />);
    expect(screen.getByTestId("feed-loading")).toBeInTheDocument();
    expect(screen.getByText("Loading feed status…")).toBeInTheDocument();
    expect(screen.queryByTestId("feed-offline")).not.toBeInTheDocument();
  });

  it("shows an error state when there is no data", () => {
    render(<FeedStatus status={null} loading={false} error={{ message: "Network down" }} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Network down");
    expect(screen.queryByTestId("feed-offline")).not.toBeInTheDocument();
  });

  it("keeps last known data visible with an error banner on refresh failure", () => {
    render(<FeedStatus status={status()} loading={false} error={{ message: "timeout" }} now={NOW} />);
    expect(screen.getByRole("alert")).toHaveTextContent("timeout");
    expect(screen.getByTestId("provider-massive")).toBeInTheDocument();
  });
});
