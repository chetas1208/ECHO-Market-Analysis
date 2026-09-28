"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { getBars, getMarketStatus, getMarketSymbols, getShocks } from "@/lib/marketApi";
import { usePolling } from "@/lib/usePolling";
import type { PollingResult } from "@/lib/usePolling";
import type { EchoEvent } from "@/types/event";
import { DEFAULT_INTERVAL, MODE_DESCRIPTION, isSyntheticMode } from "@/types/market";
import type { Bar, DataMode, Interval, MarketSymbolRow } from "@/types/market";
import { EmptyState, ErrorState } from "../StateViews";
import { FeedStatus } from "./FeedStatus";
import { ModeBadge } from "./ModeBadge";
import { PriceChart } from "./PriceChart";
import type { PriceChartMarker } from "./PriceChart";
import { ShockCard } from "./ShockCard";
import { SymbolTable } from "./SymbolTable";
import styles from "./MarketPanel.module.css";

export const OFFLINE_MESSAGE =
  "Market feed offline — set ECHO_MARKET_PROVIDER=replay to run the replay scenario";
export const NO_SHOCKS_MESSAGE = "No market shocks detected yet";

const POLL_MS = 5_000;
const BARS_POLL_MS = 10_000;
const BARS_LIMIT = 240;
/** Shocks fetched (for the count + chart markers); only the latest SHOCK_LIST_SIZE are listed. */
export const SHOCKS_FETCH_LIMIT = 50;
export const SHOCK_LIST_SIZE = 5;
const MAX_MARKERS = 5;

const INTERVAL_MS: Record<Interval, number> = { "1m": 60_000, "5m": 300_000, "15m": 900_000 };

/** What the Dashboard needs for its "Market shocks" metric card. */
export interface MarketSummary {
  mode: DataMode | null;
  /** Number of market shocks returned by the API (capped by SHOCKS_FETCH_LIMIT); null = unknown. */
  shocks: number | null;
  /** True when the shocks request failed and no earlier data exists. */
  failed: boolean;
}

/** Chart markers for one symbol, restricted to shocks that fall inside the plotted bar range. */
export function shockMarkers(
  events: readonly EchoEvent[],
  symbol: string,
  bars: readonly Bar[],
  interval: Interval,
): PriceChartMarker[] {
  const times = bars.map((b) => Date.parse(b.timestamp)).filter(Number.isFinite);
  if (times.length === 0) return [];
  const pad = INTERVAL_MS[interval];
  const lo = Math.min(...times) - pad;
  const hi = Math.max(...times) + pad;
  return events
    .filter((e) => e.companies.includes(symbol))
    .filter((e) => {
      const t = Date.parse(e.timestamp);
      return Number.isFinite(t) && t >= lo && t <= hi;
    })
    .slice(0, MAX_MARKERS)
    .map((e) => {
      const score = e.metadata?.shock_score;
      const dir = e.metadata?.direction;
      return {
        timestamp: e.timestamp,
        label: typeof score === "number" ? `Shock ${score.toFixed(2)}` : "Shock",
        direction: dir === "positive" || dir === "negative" ? dir : undefined,
      };
    });
}

function Loading({ label }: { label: string }) {
  return (
    <div role="status" aria-busy="true" className={styles.loading} data-testid="market-loading">
      <span className="sr-only">{label}</span>
      <div aria-hidden="true" className={styles.skelStack}>
        <div className={styles.skel} />
        <div className={styles.skel} />
        <div className={styles.skel} />
        <div className={styles.skel} />
      </div>
    </div>
  );
}

function StaleNote({ message }: { message: string }) {
  return (
    <p className={styles.stale} role="status" data-testid="market-stale">
      Refresh failed, showing last data: {message}
    </p>
  );
}

function ChartPane({
  symbol,
  row,
  shocks,
}: {
  symbol: string;
  row: MarketSymbolRow | undefined;
  shocks: readonly EchoEvent[];
}) {
  const [interval, setIntervalState] = useState<Interval>(DEFAULT_INTERVAL);
  const keyRef = useRef({ symbol, interval });

  // One long-lived poll; the selection lives in a ref. If it changes while a request is in
  // flight the stale response is discarded and the request repeated, so the chart never shows
  // another symbol's or interval's bars (and the interval buttons keep keyboard focus).
  const bars = usePolling(async (signal) => {
    for (;;) {
      const k = keyRef.current;
      const res = await getBars(k.symbol, { interval: k.interval, limit: BARS_LIMIT, signal });
      const cur = keyRef.current;
      if (cur.symbol === k.symbol && cur.interval === k.interval) return res;
    }
  }, BARS_POLL_MS);

  const { refresh } = bars;
  useEffect(() => {
    keyRef.current = { symbol, interval };
    refresh();
  }, [symbol, interval, refresh]);

  const fresh =
    bars.data &&
    bars.data.symbol.toUpperCase() === symbol.toUpperCase() &&
    bars.data.interval === interval
      ? bars.data
      : null;
  const items = useMemo(() => fresh?.items ?? [], [fresh]);
  const markers = useMemo(
    () => shockMarkers(shocks, symbol, items, interval),
    [shocks, symbol, items, interval],
  );

  const price = row?.price;
  const chg = row?.change_pct;
  const tone = typeof chg !== "number" || chg === 0 ? "" : chg > 0 ? styles.pos : styles.neg;

  return (
    <>
      <div className={styles.quote} data-testid="chart-quote">
        <b>{symbol}</b>
        <span>{typeof price === "number" ? price.toFixed(2) : "—"}</span>
        <span className={tone}>
          {typeof chg === "number" ? `${chg > 0 ? "+" : ""}${chg.toFixed(2)}%` : "—"}
        </span>
      </div>
      <div className={styles.chartBox}>
        <PriceChart
          bars={items}
          interval={interval}
          onIntervalChange={setIntervalState}
          markers={markers}
          height={300}
        />
        {!fresh && bars.error ? (
          <div className={styles.overlay} role="alert" data-testid="bars-error">
            <p>
              Could not load {symbol} bars: {bars.error.message}
            </p>
            <button type="button" className="btn" onClick={refresh}>
              Retry
            </button>
          </div>
        ) : null}
        {!fresh && !bars.error ? (
          <div className={styles.overlay} role="status" data-testid="bars-loading">
            Loading {symbol} {interval} bars…
          </div>
        ) : null}
      </div>
      {fresh && bars.error ? <StaleNote message={bars.error.message} /> : null}
    </>
  );
}

function SymbolsPane({
  symbols,
  selected,
  onSelect,
}: {
  symbols: PollingResult<{ items: MarketSymbolRow[] }>;
  selected: string | undefined;
  onSelect: (symbol: string) => void;
}) {
  const rows = symbols.data?.items ?? [];
  if (!symbols.data) {
    if (symbols.error) {
      return (
        <ErrorState
          title="Could not load market symbols"
          error={symbols.error}
          onRetry={symbols.refresh}
        />
      );
    }
    return <Loading label="Loading market symbols…" />;
  }
  return (
    <>
      {symbols.error ? <StaleNote message={symbols.error.message} /> : null}
      {rows.length === 0 ? (
        <EmptyState title="No tracked symbols">
          The market feed has not reported a symbol universe yet.
        </EmptyState>
      ) : (
        <div className={styles.scroll}>
          <SymbolTable rows={rows} selected={selected} onSelect={onSelect} />
        </div>
      )}
    </>
  );
}

function ShocksPane({ shocks }: { shocks: PollingResult<{ items: EchoEvent[] }> }) {
  if (!shocks.data) {
    if (shocks.error) {
      return (
        <ErrorState
          title="Could not load market shocks"
          error={shocks.error}
          onRetry={shocks.refresh}
        />
      );
    }
    return <Loading label="Loading market shocks…" />;
  }
  const latest = shocks.data.items.slice(0, SHOCK_LIST_SIZE);
  return (
    <>
      {shocks.error ? <StaleNote message={shocks.error.message} /> : null}
      {latest.length === 0 ? (
        <EmptyState title={NO_SHOCKS_MESSAGE}>
          Shocks appear here when a symbol moves abnormally versus its sector and the market.
        </EmptyState>
      ) : (
        <ul className={`${styles.scroll} ${styles.shockList}`} data-testid="shock-list">
          {latest.map((event) => (
            <li key={event.id}>
              <ShockCard event={event} />
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

/**
 * Compact Market region for the Dashboard: feed status, tracked symbols, price chart for the
 * selected symbol (with recent shock markers) and the latest detected market shocks.
 * OFFLINE mode shows an explicit empty state and never any prices.
 */
export function MarketPanel({ onSummary }: { onSummary?: (summary: MarketSummary) => void }) {
  const status = usePolling(getMarketStatus, POLL_MS);
  const symbols = usePolling(getMarketSymbols, POLL_MS);
  const shocks = usePolling((signal) => getShocks(SHOCKS_FETCH_LIMIT, signal), POLL_MS);
  const [picked, setPicked] = useState<string | null>(null);

  const mode = status.data?.mode ?? null;
  const offline = mode === "OFFLINE";
  const rows = useMemo(() => symbols.data?.items ?? [], [symbols.data]);
  const events = useMemo(() => shocks.data?.items ?? [], [shocks.data]);

  // Stable default (API order, not the live sort order) so the chart never flips by itself.
  const fallback = (rows.find((r) => r.role === "equity") ?? rows[0])?.symbol;
  const selected = picked !== null && rows.some((r) => r.symbol === picked) ? picked : fallback;
  const selectedRow = rows.find((r) => r.symbol === selected);

  const summary = useMemo<MarketSummary>(
    () => ({
      mode,
      shocks: shocks.data ? shocks.data.items.length : null,
      failed: !shocks.data && shocks.error !== null,
    }),
    [mode, shocks.data, shocks.error],
  );
  useEffect(() => {
    onSummary?.(summary);
  }, [onSummary, summary]);

  return (
    <section
      className={`panel panel--wide market-region ${styles.region}`}
      aria-labelledby="market-region-title"
      data-testid="market-panel"
    >
      <div className={styles.head}>
        <div>
          <span className="eyebrow">Market response</span>
          <h2 id="market-region-title">Market</h2>
        </div>
        {mode ? (
          <div className={styles.mode}>
            <ModeBadge mode={mode} compact />
            <span className={styles.modeText}>
              {isSyntheticMode(mode) || offline ? MODE_DESCRIPTION[mode] : null}
            </span>
          </div>
        ) : null}
      </div>

      <FeedStatus status={status.data ?? null} loading={status.loading} error={status.error} />

      <div className={`${styles.body} ${offline ? styles.bodyOffline : ""}`}>
        {offline ? (
          <div className={`${styles.col} ${styles.offlineCol}`}>
            <div className={styles.offline} role="status" data-testid="market-offline">
              <p>{OFFLINE_MESSAGE}</p>
            </div>
          </div>
        ) : (
          <>
            <div className={`${styles.col} ${styles.symCol}`}>
              <h3 className={styles.colTitle}>
                Tracked symbols{rows.length ? <span>{rows.length}</span> : null}
              </h3>
              <SymbolsPane symbols={symbols} selected={selected} onSelect={setPicked} />
            </div>
            <div className={`${styles.col} ${styles.chartCol}`}>
              <h3 className={styles.colTitle}>Price chart</h3>
              {selected ? (
                <ChartPane symbol={selected} row={selectedRow} shocks={events} />
              ) : (
                <EmptyState title="No symbol selected">
                  Select a tracked symbol to see its price chart.
                </EmptyState>
              )}
            </div>
          </>
        )}
        <div className={`${styles.col} ${styles.shockCol}`}>
          <h3 className={styles.colTitle}>Detected market shocks</h3>
          <ShocksPane shocks={shocks} />
        </div>
      </div>
    </section>
  );
}
