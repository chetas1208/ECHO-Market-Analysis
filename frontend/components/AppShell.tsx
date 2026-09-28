"use client";

import { usePathname } from "next/navigation";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Sidebar, SIDEBAR_ID } from "./Sidebar";
import { EchoMark, Icon } from "./Icons";
import { getExecutionStatus, getReady } from "@/lib/api";
import { useApiResource } from "@/lib/useApiResource";
import { MarketStatusProvider, useMarketStatus } from "@/lib/MarketStatusContext";
import { useWorldStatus, WorldStatusProvider } from "@/lib/WorldStatusContext";
import { ModeBadge } from "./market/ModeBadge";

/**
 * Global layout: a top bar with the only navigation trigger (hamburger) and a hidden vertical drawer
 * that OVERLAYS the page (UI.md 3.2, 66, 72). No permanent rail, no content push.
 */
export function AppShell({ children }: { children: ReactNode }) {
  return (
    <MarketStatusProvider>
      <WorldStatusProvider>
        <AppShellInner>{children}</AppShellInner>
      </WorldStatusProvider>
    </MarketStatusProvider>
  );
}

function AppShellInner({ children }: { children: ReactNode }) {
  const { mode } = useMarketStatus();
  const world = useWorldStatus();
  const [open, setOpen] = useState(false);
  const [utcTime, setUtcTime] = useState("--:--");
  const pathname = usePathname();
  const router = useRouter();
  const fetchReady = useCallback((signal: AbortSignal) => getReady(signal), []);
  const { state: readyState, reload: reloadReady } = useApiResource(fetchReady);
  const fetchExecution = useCallback((signal: AbortSignal) => getExecutionStatus(signal), []);
  const { state: executionState } = useApiResource(fetchExecution);

  const toggle = useCallback(() => setOpen((o) => !o), []);
  const close = useCallback(() => setOpen(false), []);

  const menuRef = useRef<HTMLButtonElement>(null);
  const wasOpen = useRef(false);

  // Drawer open: Esc closes, Tab is trapped inside the drawer, page scroll is locked
  // (without shifting content sideways), and focus returns to the hamburger on close.
  useEffect(() => {
    if (!open) {
      if (wasOpen.current) menuRef.current?.focus();
      wasOpen.current = false;
      return;
    }
    wasOpen.current = true;
    const drawer = document.getElementById(SIDEBAR_ID);
    const focusables = () =>
      Array.from(drawer?.querySelectorAll<HTMLElement>("a[href], button:not(:disabled)") ?? []);
    const first = drawer?.querySelector<HTMLElement>('[aria-current="page"]') ?? focusables()[0];
    first?.focus();

    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        return;
      }
      if (e.key !== "Tab") return;
      const items = focusables();
      const head = items[0];
      const tail = items[items.length - 1];
      if (!head || !tail) return;
      const current = document.activeElement;
      if (!drawer?.contains(current)) {
        e.preventDefault();
        head.focus();
      } else if (e.shiftKey && current === head) {
        e.preventDefault();
        tail.focus();
      } else if (!e.shiftKey && current === tail) {
        e.preventDefault();
        head.focus();
      }
    };
    window.addEventListener("keydown", onKey);

    const { body, documentElement } = document;
    const prev = { overflow: body.style.overflow, paddingRight: body.style.paddingRight };
    const scrollbar = window.innerWidth - documentElement.clientWidth;
    body.style.overflow = "hidden";
    if (scrollbar > 0) body.style.paddingRight = `${scrollbar}px`;
    return () => {
      window.removeEventListener("keydown", onKey);
      body.style.overflow = prev.overflow;
      body.style.paddingRight = prev.paddingRight;
    };
  }, [open]);

  useEffect(() => {
    const update = () => setUtcTime(new Date().toISOString().slice(11, 16));
    update();
    const id = window.setInterval(update, 30_000);
    return () => window.clearInterval(id);
  }, []);

  useEffect(() => {
    const id = window.setInterval(reloadReady, 30_000);
    return () => window.clearInterval(id);
  }, [reloadReady]);

  const submitSearch = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const input = event.currentTarget.elements.namedItem("global-search") as HTMLInputElement | null;
    const query = input?.value.trim();
    if (query) router.push(`/events?q=${encodeURIComponent(query)}`);
  };

  const isReady = readyState.status === "success" && readyState.data.status === "ready";
  const dataLabel = readyState.status === "loading" ? "CHECKING" : isReady ? "API OK" : "DEGRADED";
  const executionLabel = executionState.status === "success"
    ? executionState.data.mode === "PAPER" ? "PAPER"
      : "SIMULATION"
    : "SIMULATION";
  const systemState = isReady && world.mode !== "OFFLINE" ? "HEALTHY" : "DEGRADED";

  return (
    <div className="shell" data-open={open}>
      <a href="#main" className="skip-link">
        Skip to content
      </a>
      <Sidebar open={open} onClose={close} pathname={pathname} />
      <button
        type="button"
        className="scrim"
        tabIndex={-1}
        aria-hidden="true"
        data-open={open}
        onClick={close}
      />
      <div className="main" inert={open}>
        <header className="topbar">
          <div className="topbar__section">
            <button
              ref={menuRef}
              type="button"
              className="topbar__menu icon-btn"
              onClick={toggle}
              aria-expanded={open}
              aria-controls={SIDEBAR_ID}
              aria-label="Open navigation"
            >
              <Icon name="menu" />
            </button>
            <EchoMark />
            <span className="topbar__brand">ECHO</span>
            <span className="topbar__divider" aria-hidden="true" />
            <span className="topbar__context">{pathname === "/" ? "Dashboard" : pathname.split("/")[1] || "Dashboard"}</span>
          </div>
          <form className="global-search" onSubmit={submitSearch} role="search">
            <Icon name="search" />
            <span className="sr-only">Search ECHO</span>
            <input name="global-search" placeholder="Search events, companies, tickers..." />
            <kbd>⌘K</kbd>
          </form>
          <div className="topbar__status">
            <ModeBadge mode={mode} />
            <span className={`system-chip system-chip--${world.mode.toLowerCase()}`} title={`World feed: ${world.mode}`}>
              <span className="system-chip__dot" aria-hidden="true" />WORLD {world.mode}
            </span>
            <span className={`system-chip system-chip--${mode.toLowerCase()}`} title={`Market feed: ${mode}`}>
              <span className="system-chip__dot" aria-hidden="true" />MARKET {mode}
            </span>
            <span className={`system-chip system-chip--${executionLabel === "PAPER" ? "paper" : "paused"}`} title="Paper execution is simulated broker execution">
              <span className="system-chip__dot" aria-hidden="true" />{executionLabel}
            </span>
            <span className={`live-dot${isReady ? "" : " live-dot--degraded"}`} aria-hidden="true" />
            <span data-testid="api-health" title={`System state: ${systemState}`}>{dataLabel}</span>
            <span className="topbar__utc mono">UTC {utcTime}</span>
            <button className="avatar" type="button" aria-label="Open profile menu">CP</button>
          </div>
        </header>
        <main id="main">{children}</main>
      </div>
    </div>
  );
}
