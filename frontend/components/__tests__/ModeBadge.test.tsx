import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ModeBadge } from "../market/ModeBadge";

type Mode = "LIVE" | "REPLAY" | "MOCK" | "OFFLINE";

const CASES: [Mode, RegExp, RegExp][] = [
  ["LIVE", /^LIVE$/, /^Data mode: live/],
  ["REPLAY", /^◉ ?REPLAY$/, /^Data mode: replay \(not live market data\)$/],
  ["MOCK", /^MOCK$/, /^Data mode: mock/],
  ["OFFLINE", /^OFFLINE$/, /^Data mode: offline/],
];

describe("ModeBadge", () => {
  it.each(CASES)("%s renders correct text and aria-label", (mode, text, aria) => {
    render(<ModeBadge mode={mode} />);
    const el = screen.getByRole("status");
    expect(el.textContent?.trim()).toMatch(text);
    expect(el.getAttribute("aria-label")).toMatch(aria);
    expect(el.getAttribute("data-mode")).toBe(mode);
  });

  it.each(["REPLAY", "MOCK", "OFFLINE"] as Mode[])("%s never renders the word LIVE", (mode) => {
    const { container } = render(<ModeBadge mode={mode} />);
    expect(container.textContent).not.toMatch(/live/i);
    expect(container.querySelector("[aria-label]")?.getAttribute("aria-label")).not.toMatch(
      /^Data mode: live/,
    );
  });

  it("compact keeps text and status role", () => {
    render(<ModeBadge mode="REPLAY" compact />);
    expect(screen.getByRole("status").textContent).toContain("REPLAY");
  });
});
