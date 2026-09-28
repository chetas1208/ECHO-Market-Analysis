import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { WorldMode } from "@/types/world";
import { WorldModeChip } from "../WorldModeChip";

const CASES: [WorldMode, RegExp, string][] = [
  ["LIVE", /^WORLD LIVE$/, "World feed: live"],
  ["REPLAY", /^◉ ?WORLD REPLAY$/, "World feed: replay (not live)"],
  ["OFFLINE", /^WORLD OFFLINE$/, "World feed: offline (no world events)"],
];

describe("WorldModeChip", () => {
  it.each(CASES)("%s renders text and aria-label", (mode, text, aria) => {
    render(<WorldModeChip mode={mode} />);
    const el = screen.getByRole("status");
    expect(el.textContent?.trim()).toMatch(text);
    expect(el.getAttribute("aria-label")).toBe(aria);
    expect(el.getAttribute("data-mode")).toBe(mode);
  });

  it.each(["REPLAY", "OFFLINE"] as WorldMode[])("%s never says LIVE", (mode) => {
    const { container } = render(<WorldModeChip mode={mode} />);
    expect(container.textContent).not.toMatch(/live/i);
    const aria = screen.getByRole("status").getAttribute("aria-label") ?? "";
    expect(aria).not.toMatch(/: live/i);
  });

  it("LIVE is the only mode whose text contains LIVE", () => {
    const modes: WorldMode[] = ["LIVE", "REPLAY", "OFFLINE"];
    const withLive = modes.filter((m) => {
      const { container, unmount } = render(<WorldModeChip mode={m} />);
      const has = /live/i.test(container.textContent ?? "");
      unmount();
      return has;
    });
    expect(withLive).toEqual(["LIVE"]);
  });

  it("an unexpected runtime value falls back to OFFLINE, never LIVE", () => {
    render(<WorldModeChip mode={"BOGUS" as unknown as WorldMode} />);
    const el = screen.getByRole("status");
    expect(el.textContent).toMatch(/WORLD OFFLINE/);
    expect(el.getAttribute("data-mode")).toBe("OFFLINE");
  });
});
