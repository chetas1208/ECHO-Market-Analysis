import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AppShell } from "../AppShell";

vi.mock("next/navigation", () => ({
  usePathname: () => "/events",
  useRouter: () => ({ push: vi.fn() }),
}));
vi.mock("next/link", () => ({
  default: ({ href, children, onClick, ...rest }: { href: string; children: React.ReactNode; onClick?: () => void }) => (
    <a
      href={href}
      onClick={(e) => {
        e.preventDefault();
        onClick?.();
      }}
      {...rest}
    >
      {children}
    </a>
  ),
}));

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new TypeError("offline"))));
});

describe("AppShell navigation (UI.md 3.2 / 66)", () => {
  it("exposes exactly the five primary destinations, only inside the drawer", () => {
    const { container } = render(<AppShell>content</AppShell>);
    const drawer = container.querySelector("aside") as HTMLElement;
    const labels = Array.from(drawer.querySelectorAll("nav a")).map((a) => a.textContent);
    expect(labels).toEqual(["Dashboard", "Events", "Graph", "Forecasts", "Strategy"]);
    expect(container.querySelectorAll("header a")).toHaveLength(0);
  });

  it("keeps the drawer inert while closed and inerts the page while open", () => {
    const { container } = render(<AppShell>content</AppShell>);
    const drawer = container.querySelector("aside") as HTMLElement;
    const page = container.querySelector(".main") as HTMLElement;
    expect(drawer).toHaveAttribute("inert");
    expect(page).not.toHaveAttribute("inert");

    fireEvent.click(screen.getByRole("button", { name: "Open navigation" }));
    expect(drawer).not.toHaveAttribute("inert");
    expect(page).toHaveAttribute("inert");
    expect(document.body.style.overflow).toBe("hidden");
  });

  it("closes on Escape, restores scroll, and returns focus to the hamburger", () => {
    render(<AppShell>content</AppShell>);
    const hamburger = screen.getByRole("button", { name: "Open navigation" });
    fireEvent.click(hamburger);
    expect(hamburger).toHaveAttribute("aria-expanded", "true");
    fireEvent.keyDown(window, { key: "Escape" });
    expect(hamburger).toHaveAttribute("aria-expanded", "false");
    expect(document.body.style.overflow).toBe("");
    expect(document.activeElement).toBe(hamburger);
  });

  it("closes from the drawer close button, the backdrop, and on item selection", () => {
    const { container } = render(<AppShell>content</AppShell>);
    const hamburger = screen.getByRole("button", { name: "Open navigation" });
    const expanded = () => hamburger.getAttribute("aria-expanded");

    fireEvent.click(hamburger);
    fireEvent.click(screen.getByRole("button", { name: "Close navigation" }));
    expect(expanded()).toBe("false");

    fireEvent.click(hamburger);
    fireEvent.click(container.querySelector(".scrim") as HTMLElement);
    expect(expanded()).toBe("false");

    fireEvent.click(hamburger);
    fireEvent.click(screen.getByRole("link", { name: "Graph" }));
    expect(expanded()).toBe("false");
  });

  it("traps Tab inside the open drawer", () => {
    const { container } = render(<AppShell>content</AppShell>);
    fireEvent.click(screen.getByRole("button", { name: "Open navigation" }));
    const items = container.querySelectorAll<HTMLElement>("aside a[href], aside button");
    const last = items[items.length - 1] as HTMLElement;
    last.focus();
    fireEvent.keyDown(window, { key: "Tab" });
    expect(document.activeElement).toBe(items[0]);
    fireEvent.keyDown(window, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(last);
  });
});
