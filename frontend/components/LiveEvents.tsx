"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { API_BASE_URL } from "@/lib/api";
import type { EventSourceFilter } from "@/lib/eventsApi";
import { usePolling } from "@/lib/usePolling";
import { useWorldStatus, WorldStatusProvider } from "@/lib/WorldStatusContext";
import { listEventsWithFilters } from "@/lib/worldApi";
import type { EchoEvent } from "@/types/event";
import type { EventCategory } from "@/types/world";
import { EventList } from "./EventList";
import { PageHeader } from "./PageHeader";
import { WorldModeChip } from "./WorldModeChip";
import styles from "./Events.module.css";

const PAGE_SIZE = 20;
/** Auto-refresh cadence for the feed. */
export const EVENTS_POLL_MS = 10_000;

/** One unified feed: world events, market shocks and financial events share one list. */
const FILTERS: ReadonlyArray<{ value: EventSourceFilter; label: string; noun: string }> = [
  { value: "all", label: "All", noun: "events" },
  { value: "world", label: "World", noun: "world events" },
  { value: "market", label: "Market shocks", noun: "market shocks" },
  { value: "financial", label: "Financial", noun: "financial events" },
];

type CategoryFilter = EventCategory | "all";
type SeverityFilter = "any" | "0.5" | "0.7";
type FilterId = "source" | "category" | "severity";

/** Category groups are filters, never navigation (UI.md). "other" is left out of the chip row. */
const CATEGORIES: ReadonlyArray<{ value: CategoryFilter; label: string; aria?: string }> = [
  { value: "all", label: "All", aria: "All categories" },
  { value: "geopolitics", label: "Geopolitics" },
  { value: "energy", label: "Energy" },
  { value: "supply_chain", label: "Supply chain" },
  { value: "technology", label: "Technology" },
  { value: "macro", label: "Macro" },
];

/** Heuristic severity floors (ELEVATED >= 0.5, HIGH >= 0.7); these are scores, not probabilities. */
const SEVERITIES: ReadonlyArray<{ value: SeverityFilter; label: string }> = [
  { value: "any", label: "Any" },
  { value: "0.5", label: "Elevated+" },
  { value: "0.7", label: "High" },
];

interface Filters {
  source: EventSourceFilter;
  category: CategoryFilter;
  severity: SeverityFilter;
}

function eventsHref(query: string, page: number): string {
  const params = new URLSearchParams();
  if (query.trim()) params.set("q", query.trim());
  if (page > 1) params.set("page", String(page));
  const suffix = params.toString();
  return `/events${suffix ? `?${suffix}` : ""}`;
}

/**
 * Live Events page body. The filter lives here; the polling feed is a keyed child so switching
 * filter / page starts a clean poll (no stale rows from the previous filter) while the 10 s
 * auto-refresh itself keeps the current rows on screen (no flicker).
 */
export function LiveEvents(props: { initialQuery?: string; initialOffset?: number }) {
  return (
    <WorldStatusProvider>
      <LiveEventsInner {...props} />
    </WorldStatusProvider>
  );
}

function LiveEventsInner({ initialQuery = "", initialOffset = 0 }: { initialQuery?: string; initialOffset?: number }) {
  const router = useRouter();
  const [filters, setFilters] = useState<Filters>({ source: "all", category: "all", severity: "any" });
  // Offset at which a filter change reset us to page 1 (until the URL catches up).
  const [resetFrom, setResetFrom] = useState<number | null>(null);
  if (resetFrom !== null && resetFrom !== initialOffset) setResetFrom(null);
  const offset = resetFrom === initialOffset ? 0 : initialOffset;
  // Feed key + control at which keyboard focus goes back (the feed remounts per key).
  const [focus, setFocus] = useState<{ key: string; id: FilterId } | null>(null);
  const keyFor = (f: Filters, off: number) => `${f.source}:${f.category}:${f.severity}:${off}`;
  const feedKey = keyFor(filters, offset);

  const onFilter = (id: FilterId, patch: Partial<Filters>) => {
    const next = { ...filters, ...patch };
    if (next.source === filters.source && next.category === filters.category && next.severity === filters.severity) {
      return;
    }
    setFocus({ key: keyFor(next, initialOffset > 0 ? 0 : offset), id });
    setFilters(next);
    if (initialOffset > 0) {
      setResetFrom(initialOffset);
      router.replace(eventsHref(initialQuery, 1));
    }
  };

  return (
    <EventsFeed
      key={feedKey}
      filters={filters}
      onFilter={onFilter}
      offset={offset}
      query={initialQuery}
      focusOnMount={focus?.key === feedKey ? focus.id : null}
    />
  );
}

function EventsFeed({
  filters,
  onFilter,
  offset,
  query: rawQuery,
  focusOnMount,
}: {
  filters: Filters;
  onFilter: (id: FilterId, patch: Partial<Filters>) => void;
  offset: number;
  query: string;
  focusOnMount: FilterId | null;
}) {
  const { source: filter, category, severity } = filters;
  const { data, error, loading, lastUpdated, refresh } = usePolling(
    (signal) =>
      listEventsWithFilters({
        limit: PAGE_SIZE,
        offset,
        sourceType: filter,
        category: category === "all" ? undefined : category,
        severityMin: severity === "any" ? undefined : Number(severity),
        signal,
      }),
    EVENTS_POLL_MS,
  );
  const rowRef = useRef<HTMLDivElement>(null);
  const world = useWorldStatus();
  const query = rawQuery.trim().toLowerCase();
  const now = lastUpdated?.getTime();

  // The feed remounts on filter change; hand keyboard focus back to the control that changed.
  useEffect(() => {
    if (!focusOnMount) return;
    const el = rowRef.current?.querySelector<HTMLElement>(`[data-filter="${focusOnMount}"]`);
    if (!el) return;
    (el instanceof HTMLSelectElement ? el : el.querySelector<HTMLButtonElement>('button[aria-pressed="true"]'))?.focus();
  }, [focusOnMount]);

  // Client-side fallback: if the backend ignores `source_type`, still show only the chosen kind.
  const { events, filteredLocally } = useMemo(() => {
    const items: EchoEvent[] = data?.items ?? [];
    const byFilter = filter === "all" ? items : items.filter((e) => e.source_type === filter);
    const byQuery = query
      ? byFilter.filter((e) =>
          [e.title, e.event_type, e.summary ?? "", ...e.companies, ...e.entities, ...e.locations]
            .join(" ")
            .toLowerCase()
            .includes(query),
        )
      : byFilter;
    return { events: byQuery, filteredLocally: byFilter.length !== items.length };
  }, [data, filter, query]);

  let meta: string;
  if (data) {
    const { total } = data;
    if (filteredLocally) {
      meta = `${events.length} matching on this page · filtered locally · newest first`;
    } else {
      const first = total ? offset + 1 : 0;
      const last = offset + events.length;
      meta = `${first}–${last} of ${total} ${total === 1 ? "event" : "events"} · newest first`;
    }
  } else if (loading) {
    meta = "loading…";
  } else {
    meta = "unavailable";
  }

  const noun = FILTERS.find((f) => f.value === filter)?.noun ?? "events";
  const narrowed = category !== "all" || severity !== "any";

  let body;
  if (data) {
    body = events.length ? (
      <>
        {error ? (
          <p className={styles.stale} role="status">
            Refresh failed ({error.message}). Showing the last successful update; retrying automatically.
          </p>
        ) : null}
        <EventList status="success" events={events} now={now} />
        <Pagination offset={offset} total={data.total} query={rawQuery} />
      </>
    ) : (
      <div className="state-box">
        <p className="state-box__title">
          {query
            ? `No ${filter === "all" ? "events" : noun} match “${query}”`
            : narrowed
              ? `No ${filter === "all" ? "events" : noun} match these filters`
              : filter === "all"
                ? "No events returned"
                : `No ${noun} returned`}
        </p>
        <p className="muted">
          {query
            ? "Try a company, ticker, location, or event type."
            : narrowed
              ? "Nothing matches the category / severity filters yet. Choose Any severity or All categories to widen."
              : filter === "all"
                ? "Wait for the event feed or seed the local fixture."
                : "Nothing matches this filter yet. Choose All to see every event."}
        </p>
      </div>
    );
  } else if (error) {
    body = <EventList status="error" error={error} onRetry={refresh} />;
  } else {
    body = <EventList status="loading" />;
  }

  return (
    <div className={styles.page}>
      <PageHeader
        title="Live Events"
        meta={
          <>{meta} · auto-refresh {EVENTS_POLL_MS / 1000}s · <span title="NEXT_PUBLIC_API_URL">{API_BASE_URL}</span></>
        }
        actions={
          <>
            {world.loading ? null : <WorldModeChip mode={world.mode} />}
            <button type="button" className="btn" onClick={refresh} disabled={loading && !data}>
              Refresh
            </button>
          </>
        }
      />
      <div ref={rowRef} className={styles.filtersRow}>
        <div className={styles.filterGroup}>
          <span className="label">Source</span>
          <div className={styles.filters} data-filter="source" role="group" aria-label="Filter events by source">
            {FILTERS.map((f) => (
              <button
                key={f.value}
                type="button"
                className={styles.filterBtn}
                aria-pressed={filter === f.value}
                onClick={() => onFilter("source", { source: f.value })}
              >
                {f.label}
              </button>
            ))}
          </div>
        </div>
        <div className={styles.filterGroup}>
          <span className="label">Category</span>
          <div className={styles.filters} data-filter="category" role="group" aria-label="Filter events by category">
            {CATEGORIES.map((c) => (
              <button
                key={c.value}
                type="button"
                className={styles.filterBtn}
                aria-pressed={category === c.value}
                aria-label={c.aria}
                onClick={() => onFilter("category", { category: c.value })}
              >
                {c.label}
              </button>
            ))}
          </div>
        </div>
        <label className={styles.filterGroup}>
          <span className="label">Severity</span>
          <select
            className={styles.select}
            data-filter="severity"
            aria-label="Minimum severity"
            title="Heuristic severity score floor (Elevated+ = 0.5, High = 0.7)"
            value={severity}
            onChange={(e) => onFilter("severity", { severity: e.target.value as SeverityFilter })}
          >
            {SEVERITIES.map((sv) => (
              <option key={sv.value} value={sv.value}>
                {sv.label}
              </option>
            ))}
          </select>
        </label>
      </div>
      {body}
    </div>
  );
}

function Pagination({ offset, total, query }: { offset: number; total: number; query: string }) {
  const page = Math.floor(offset / PAGE_SIZE) + 1;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const href = (nextPage: number) => eventsHref(query, nextPage);
  if (pages <= 1) return null;
  return <nav className="pagination" aria-label="Events pagination"><span className="pagination__summary">Page {page} of {pages}</span><div><Link className={`btn${page <= 1 ? " btn--disabled" : ""}`} aria-disabled={page <= 1} href={page > 1 ? href(page - 1) : href(page)}>Previous</Link><Link className={`btn${page >= pages ? " btn--disabled" : ""}`} aria-disabled={page >= pages} href={page < pages ? href(page + 1) : href(page)}>Next</Link></div></nav>;
}
