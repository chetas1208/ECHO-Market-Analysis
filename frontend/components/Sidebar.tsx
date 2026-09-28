"use client";

import Link from "next/link";
import { EchoMark, Icon, type IconName } from "./Icons";

interface NavItem {
  label: string;
  icon: IconName;
  href: string;
}

const NAV_ITEMS: NavItem[] = [
  { label: "Dashboard", icon: "dashboard", href: "/" },
  { label: "Events", icon: "events", href: "/events" },
  { label: "Graph", icon: "graph", href: "/graph" },
  { label: "Forecasts", icon: "forecast", href: "/forecasts" },
  { label: "Strategy", icon: "analytics", href: "/strategy" },
];

export const SIDEBAR_ID = "app-sidebar";

/** Overlay navigation drawer. Hidden (inert, unfocusable) until the top-bar hamburger opens it. */
export function Sidebar({
  open,
  onClose,
  pathname,
}: {
  open: boolean;
  onClose: () => void;
  pathname: string;
}) {
  // Events also owns its child route /events/[id].
  const isActive = (href: string) =>
    href === "/" ? pathname === "/" : pathname.startsWith(href);

  return (
    <aside id={SIDEBAR_ID} className="sidebar" data-open={open} inert={!open} aria-label="Primary">
      <div className="sidebar__top">
        <button type="button" className="icon-btn sidebar__close" onClick={onClose} aria-label="Close navigation">
          <Icon name="close" />
        </button>
        <span className="brand">
          <EchoMark />
          <span className="brand__word">ECHO</span>
        </span>
      </div>

      <nav id="sidebar-nav" aria-label="Main">
        <ul className="nav">
          {NAV_ITEMS.map((item) => {
            const active = isActive(item.href);
            return (
              <li key={item.label}>
                <Link
                  href={item.href}
                  className={`nav__item${active ? " nav__item--active" : ""}`}
                  aria-current={active ? "page" : undefined}
                  aria-label={item.label}
                  title={item.label}
                  onClick={onClose}
                >
                    <Icon name={item.icon} />
                    <span className="sidebar__label">{item.label}</span>
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>

      <div className="sidebar__foot sidebar__label">
        <span className="sidebar__utility">Data sources</span>
        <span className="sidebar__utility">Model status</span>
        <span className="sidebar__version mono">ECHO / PAPER / v0.1</span>
      </div>
    </aside>
  );
}
