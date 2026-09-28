import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { PriceChart } from "../market/PriceChart";
import type { Bar } from "@/types/market";

const T0 = Date.UTC(2026, 0, 5, 14, 30);

function mk(n: number, price = (i: number) => 100 + i): Bar[] {
  return Array.from({ length: n }, (_, i) => {
    const c = price(i);
    return {
      timestamp: new Date(T0 + i * 60_000).toISOString(),
      open: c,
      high: c + 1,
      low: c - 1,
      close: c,
      volume: 1000,
      source: "replay" as const,
    };
  });
}

const noop = () => {};

describe("PriceChart", () => {
  it("renders a line path with N points and the last-price tag", () => {
    render(<PriceChart bars={mk(10)} interval="1m" onIntervalChange={noop} />);
    const line = screen.getByTestId("price-line");
    expect(line.getAttribute("data-points")).toBe("10");
    const d = line.getAttribute("d") ?? "";
    expect(d.startsWith("M")).toBe(true);
    expect(d.match(/[ML]/g)).toHaveLength(10);
    expect(d).not.toMatch(/NaN|Infinity/);
    expect(screen.getByTestId("last-price").textContent).toBe("109.00");
    expect(screen.getByTestId("axis-max").textContent).toBe("109.00");
    expect(screen.getByTestId("axis-min").textContent).toBe("100.00");
    const ticks = screen.getAllByTestId("time-tick").map((t) => t.textContent);
    expect(ticks[0]).toBe("14:30");
    expect(ticks[ticks.length - 1]).toBe("14:39");
    expect(screen.getByRole("img").getAttribute("viewBox")).toBe("0 0 640 260");
  });

  it("positions a marker at the nearest bar", () => {
    const bars = mk(11);
    render(
      <PriceChart
        bars={bars}
        interval="1m"
        onIntervalChange={noop}
        markers={[
          { timestamp: new Date(T0 + 4 * 60_000 + 20_000).toISOString(), label: "NVDA shock", direction: "negative" },
        ]}
      />,
    );
    const m = screen.getByTestId("chart-marker");
    expect(m.getAttribute("data-bar-index")).toBe("4");
    expect(m.textContent).toContain("NVDA shock");
    const x = Number(m.querySelector("line")?.getAttribute("x1"));
    const path = screen.getByTestId("price-line").getAttribute("d") ?? "";
    const xs = path.match(/[ML]([\d.]+)/g)!.map((s) => Number(s.slice(1)));
    expect(x).toBeCloseTo(xs[4] ?? NaN, 1);
  });

  it("handles a flat series without NaN", () => {
    const { container } = render(
      <PriceChart bars={mk(5, () => 50)} interval="5m" onIntervalChange={noop} />,
    );
    expect(container.innerHTML).not.toMatch(/NaN|Infinity/);
    expect(screen.getByTestId("price-line").getAttribute("data-points")).toBe("5");
    expect(screen.getByTestId("last-price").textContent).toBe("50.00");
  });

  it("handles a single bar", () => {
    const { container } = render(
      <PriceChart bars={mk(1)} interval="5m" onIntervalChange={noop} markers={[{ timestamp: mk(1)[0]!.timestamp, label: "x" }]} />,
    );
    expect(container.innerHTML).not.toMatch(/NaN|Infinity/);
    expect(screen.getByTestId("price-line").getAttribute("data-points")).toBe("1");
    expect(screen.getByTestId("chart-marker").getAttribute("data-bar-index")).toBe("0");
  });

  it("shows empty state with no bars", () => {
    render(<PriceChart bars={[]} interval="5m" onIntervalChange={noop} />);
    expect(screen.getByText("No bars yet")).toBeInTheDocument();
    expect(screen.queryByTestId("price-line")).toBeNull();
    expect(screen.getByRole("radiogroup")).toBeInTheDocument();
  });

  it("interval selector calls back on click and arrow keys", () => {
    const onChange = vi.fn();
    render(<PriceChart bars={mk(3)} interval="5m" onIntervalChange={onChange} />);
    expect(screen.getByRole("radio", { name: "5m" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("radio", { name: "5m" })).toHaveAttribute("tabindex", "0");
    expect(screen.getByRole("radio", { name: "1m" })).toHaveAttribute("tabindex", "-1");
    fireEvent.click(screen.getByRole("radio", { name: "15m" }));
    expect(onChange).toHaveBeenLastCalledWith("15m");
    fireEvent.keyDown(screen.getByRole("radio", { name: "5m" }), { key: "ArrowRight" });
    expect(onChange).toHaveBeenLastCalledWith("15m");
    fireEvent.keyDown(screen.getByRole("radio", { name: "5m" }), { key: "ArrowLeft" });
    expect(onChange).toHaveBeenLastCalledWith("1m");
  });
});
