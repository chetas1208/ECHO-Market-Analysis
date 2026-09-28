import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ChannelList, channelLabel } from "../ChannelList";

describe("ChannelList", () => {
  it("formats labels", () => {
    expect(channelLabel("oil_supply")).toBe("Oil supply");
    expect(channelLabel("global_trade")).toBe("Global trade");
  });

  it("sorts by absolute value descending with signed 2-decimal values", () => {
    render(<ChannelList channels={{ a_small: 0.1, b_big: -0.9, c_mid: 0.5 }} />);
    const rows = screen.getAllByTestId("channel-row");
    expect(rows.map((r) => within(r).getByTitle(/_/).textContent)).toEqual(["B big", "C mid", "A small"]);
    expect(rows[0]).toHaveTextContent("-0.90");
    expect(rows[1]).toHaveTextContent("+0.50");
    expect(rows[2]).toHaveTextContent("+0.10");
  });

  it("clamps to [-1, 1] and never shows NaN", () => {
    render(<ChannelList channels={{ hi: 5, lo: -3, bad: Number.NaN, inf: Number.POSITIVE_INFINITY }} />);
    const text = document.body.textContent ?? "";
    expect(text).not.toContain("NaN");
    expect(text).toContain("+1.00");
    expect(text).toContain("-1.00");
    expect(text).toContain("0.00");
    expect(text).not.toContain("5.00");
  });

  it("shows the empty state (abstention) without the legend", () => {
    render(<ChannelList channels={{}} />);
    expect(screen.getByText("No economic channels identified")).toBeInTheDocument();
    expect(screen.queryByText(/Directional pressure/)).not.toBeInTheDocument();
  });

  it("shows the legend text", () => {
    render(<ChannelList channels={{ oil_supply: -0.8 }} />);
    expect(screen.getByText("Directional pressure (−1 … +1) — not an expected price move")).toBeInTheDocument();
  });

  it("toggles evidence with an accessible disclosure button", () => {
    render(
      <ChannelList
        channels={{ oil_supply: -0.8, energy_prices: 0.4 }}
        evidence={{ oil_supply: ["class:shipping_disruption", "entity:Strait of Hormuz"] }}
      />,
    );
    // Only channels with evidence get a toggle.
    expect(screen.getAllByRole("button")).toHaveLength(1);
    const btn = screen.getByRole("button", { name: /Evidence for Oil supply/ });
    expect(btn).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("class:shipping_disruption")).not.toBeInTheDocument();
    fireEvent.click(btn);
    expect(btn).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("class:shipping_disruption")).toBeInTheDocument();
    expect(screen.getByText("entity:Strait of Hormuz")).toBeInTheDocument();
    fireEvent.click(btn);
    expect(btn).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("class:shipping_disruption")).not.toBeInTheDocument();
  });
});
