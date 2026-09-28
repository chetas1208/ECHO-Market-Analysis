import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { MarketSymbolRow } from "@/types/market";
import { SymbolTable, sortRows } from "../market/SymbolTable";

// Test fixtures only (mirror the API contract).
function row(over: Partial<MarketSymbolRow>): MarketSymbolRow {
  return {
    symbol: "AAA",
    group: "Tech",
    role: "equity",
    sector_benchmark: null,
    price: 100,
    change_pct: 0,
    as_of: "2026-09-20T14:00:00Z",
    state: "NORMAL",
    shock_score: null,
    volume_z: 0,
    return_5m: null,
    sector_residual: null,
    direction: null,
    ...over,
  };
}

const ROWS: MarketSymbolRow[] = [
  row({ symbol: "SPY", role: "benchmark", group: "Index", change_pct: 3.5 }),
  row({ symbol: "SMALL", change_pct: -0.2 }),
  row({ symbol: "BIG", change_pct: 2.5 }),
  row({ symbol: "SHK", state: "SHOCK", change_pct: 0.1, shock_score: 0.862, direction: "negative", volume_z: 4.2 }),
  row({ symbol: "NUL", state: "NO_DATA", price: null, change_pct: null, volume_z: null }),
];

const order = () =>
  screen
    .getAllByRole("row")
    .slice(1)
    .map((r) => r.getAttribute("data-symbol"));

describe("SymbolTable", () => {
  it("sorts shocks first, then |change|, nulls last, benchmarks separated at the bottom", () => {
    render(<SymbolTable rows={ROWS} />);
    expect(order()).toEqual(["SHK", "BIG", "SMALL", "NUL", "SPY"]);
    expect(sortRows(ROWS).map((r) => r.symbol)).toEqual(order());
  });

  it("highlights shock rows and marks benchmarks", () => {
    render(<SymbolTable rows={ROWS} />);
    const rows = screen.getAllByRole("row");
    const shk = rows.find((r) => r.getAttribute("data-symbol") === "SHK")!;
    const big = rows.find((r) => r.getAttribute("data-symbol") === "BIG")!;
    const spy = rows.find((r) => r.getAttribute("data-symbol") === "SPY")!;
    expect(shk.className).toMatch(/shock/);
    expect(big.className).not.toMatch(/shock/);
    expect(spy.getAttribute("data-role")).toBe("benchmark");
    expect(spy.className).toMatch(/benchmark/);
    expect(within(shk).getByText("SHOCK")).toBeTruthy();
    expect(within(shk).getByLabelText("direction down")).toBeTruthy();
  });

  it("renders em dash for null values", () => {
    render(<SymbolTable rows={ROWS} />);
    const nul = screen.getAllByRole("row").find((r) => r.getAttribute("data-symbol") === "NUL")!;
    const cells = within(nul).getAllByRole("cell");
    // group, price, chg, volz, state, score
    expect(cells.map((c) => c.textContent)).toEqual(["Tech", "—", "—", "—", "NO DATA", "—"]);
  });

  it("calls onSelect on click and Enter", () => {
    const onSelect = vi.fn();
    render(<SymbolTable rows={ROWS} selected="BIG" onSelect={onSelect} />);
    const rows = screen.getAllByRole("row");
    const small = rows.find((r) => r.getAttribute("data-symbol") === "SMALL")!;
    fireEvent.click(small);
    expect(onSelect).toHaveBeenLastCalledWith("SMALL");
    const shk = rows.find((r) => r.getAttribute("data-symbol") === "SHK")!;
    expect(shk.tabIndex).toBe(0);
    fireEvent.keyDown(shk, { key: "Enter" });
    expect(onSelect).toHaveBeenLastCalledWith("SHK");
    expect(rows.find((r) => r.getAttribute("data-symbol") === "BIG")!.getAttribute("aria-current")).toBe("true");
  });

  it("shows shock score as a plain 0-1 number with no percent sign", () => {
    render(<SymbolTable rows={ROWS} />);
    const shk = screen.getAllByRole("row").find((r) => r.getAttribute("data-symbol") === "SHK")!;
    const score = within(shk).getByLabelText("score 0.86");
    expect(score.textContent).toBe("0.86");
    expect(score.textContent).not.toContain("%");
    expect(screen.getByRole("columnheader", { name: "Score" })).toBeTruthy();
  });

  it("is not focusable per row without onSelect", () => {
    render(<SymbolTable rows={ROWS} />);
    expect(screen.getAllByRole("row")[1]?.getAttribute("tabindex")).toBeNull();
  });
});
