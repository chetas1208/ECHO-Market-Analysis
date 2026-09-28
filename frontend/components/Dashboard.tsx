"use client";

import Link from "next/link";
import { useState } from "react";
import { useApiResource } from "@/lib/useApiResource";
import { listEvents } from "@/lib/api";
import { formatRelative } from "@/lib/format";
import { Icon } from "./Icons";
import { LoadingState, ErrorState, EmptyState } from "./StateViews";
import { MarketPanel, SHOCKS_FETCH_LIMIT } from "./market/MarketPanel";
import type { MarketSummary } from "./market/MarketPanel";
import type { EchoEvent } from "@/types/event";
import styles from "./Dashboard.module.css";

const fetchEvents = (signal: AbortSignal) => listEvents({ limit: 6, offset: 0, signal });

function Metric({ label, value, detail, tone = "default" }: { label: string; value: string; detail: string; tone?: string }) {
  return <article className={`metric metric--${tone}`}><span className="label">{label}</span><strong>{value}</strong><span className="metric__detail">{detail}</span></article>;
}

function ShockMap({ events }: { events: EchoEvent[] }) {
  return <section className="panel panel--map" aria-labelledby="shock-map-title">
    <div className="panel__head"><div><span className="eyebrow">Spatial context</span><h2 id="shock-map-title">Global shock map</h2></div><span className="panel__status"><span className="status-dot status-dot--cyan" />{events.length ? `${events.length} active` : "No active shocks"}</span></div>
    <div className="shock-map" role="img" aria-label="Abstract world region map showing active shock locations">
      <div className="map-grid" />
      <div className="map-contour map-contour--one" /><div className="map-contour map-contour--two" />
      {events.slice(0, 4).map((event, index) => <Link key={event.id} href={`/events/${encodeURIComponent(event.id)}`} className={`map-marker map-marker--${index + 1}`} aria-label={`Open ${event.title}`}><span /><b>{index + 1}</b></Link>)}
      {!events.length ? <div className="map-empty">Waiting for world-event coordinates</div> : null}
      <div className="map-legend"><span><i className="legend-dot legend-dot--red" />high severity</span><span><i className="legend-dot legend-dot--amber" />monitoring</span></div>
    </div>
  </section>;
}

function Opportunity({ event }: { event?: EchoEvent }) {
  return <section className="panel opportunity" aria-labelledby="opportunity-title">
    <div className="panel__head"><div><span className="eyebrow">Forecast workspace</span><h2 id="opportunity-title">Highest opportunity</h2></div><span className="quiet-badge">OPEN</span></div>
    {event ? <>
      <div className="opportunity__asset"><div><span className="ticker">{event.companies[0] ?? "—"}</span><span className="muted"> · event context</span></div><span className="quiet-badge">NOT GENERATED</span></div>
      <p className="opportunity__title">{event.title}</p>
      <div className="unavailable-panel"><strong>Forecast service not connected</strong><p>Validated distributions, horizons, and trade simulations will appear when the Forecast API is available.</p></div>
      <div className="opportunity__grid"><div><span className="label">prob. positive</span><b>—</b></div><div><span className="label">confidence</span><b>—</b></div><div><span className="label">horizon</span><b>—</b></div></div>
      <div className="panel__actions"><Link className="btn btn--primary" href={`/events/${encodeURIComponent(event.id)}`}>Open event</Link><Link className="btn" href="/forecasts">Forecast workspace</Link></div>
    </> : <EmptyState title="No forecast opportunities"><span>Forecasts will appear when an event has a validated asset response.</span></EmptyState>}
  </section>;
}

/** Value + detail for the "Market shocks" metric, from the Market region's live summary. */
function shockMetric(summary: MarketSummary | null): { value: string; detail: string } {
  if (!summary) return { value: "—", detail: "awaiting data" };
  if (summary.mode === "OFFLINE") return { value: "—", detail: "market feed offline" };
  if (summary.failed) return { value: "—", detail: "service unavailable" };
  if (summary.shocks === null) return { value: "—", detail: "awaiting data" };
  const capped = summary.shocks >= SHOCKS_FETCH_LIMIT;
  return { value: `${summary.shocks}${capped ? "+" : ""}`, detail: "detected, newest first" };
}

function Accuracy() {
  return <section className="panel accuracy" aria-labelledby="accuracy-title"><div className="panel__head"><div><span className="eyebrow">Reality check</span><h2 id="accuracy-title">Prediction performance</h2></div><span className="quiet-badge">MATURING</span></div><div className="accuracy__hero"><strong>—</strong><span>directional accuracy</span></div><div className="accuracy__rows"><div><span>MAE</span><b>—</b></div><div><span>interval coverage</span><b>—</b></div><div><span>matured predictions</span><b>0</b></div></div><p className="muted small">Evaluation appears as forecast horizons mature.</p></section>;
}

export function Dashboard() {
  const { state, reload } = useApiResource(fetchEvents);
  const [marketSummary, setMarketSummary] = useState<MarketSummary | null>(null);
  const shocks = shockMetric(marketSummary);
  const events = state.status === "success" ? state.data.items : [];
  const activeEvent = events[0];
  const active = state.status === "success" ? String(state.data.total) : "—";
  const freshness = state.status === "success" && state.data.items[0] ? formatRelative(state.data.items[0].ingested_at) : "awaiting data";
  return <div className={styles.page}>
    <div className="page-head page-head--dashboard"><div><span className="eyebrow">Market intelligence / overview</span><h1 className="page-head__title">Dashboard</h1><p className="page-head__lead">What requires attention right now.</p></div><div className="page-head__actions"><span className="data-freshness"><span className="status-dot status-dot--green" />{freshness}</span><button type="button" className="btn" onClick={reload} disabled={state.status === "loading"}><Icon name="pulse" /> Refresh</button></div></div>
    <div className="metric-grid"><Metric label="Events returned" value={active} detail={state.status === "success" ? "newest first" : "awaiting data"} tone="cyan" /><Metric label="Market shocks" value={shocks.value} detail={shocks.detail} tone="red" /><Metric label="Forecast opportunities" value="—" detail="service unavailable" tone="purple" /><Metric label="Directional accuracy" value="—" detail="no matured data" /><Metric label="Paper portfolio P&L" value="—" detail="service unavailable" tone="green" /></div>
    <div className="dashboard-grid">
      {state.status === "loading" ? <div className={styles.eventsState}><LoadingState rows={1} /></div> : state.status === "error" ? <div className={styles.eventsState}><ErrorState title="Live event feed unavailable" error={state.error} onRetry={reload} /></div> : <>
      <section className="panel live-panel" aria-labelledby="live-events-title"><div className="panel__head"><div><span className="eyebrow">World monitor</span><h2 id="live-events-title">Live events</h2></div><Link className="panel__link" href="/events">View all <span aria-hidden="true">→</span></Link></div>{events.length ? <ul className="dashboard-events">{events.map((event) => <li key={event.id}><Link href={`/events/${encodeURIComponent(event.id)}`}><span className={`event-severity event-severity--${event.severity > .75 ? "high" : "medium"}`} /> <div><strong>{event.title}</strong><span>{event.event_type.replaceAll("_", " ")} · {formatRelative(event.timestamp)}</span></div><span className="event-confidence mono">{Math.round(event.confidence * 100)}%</span></Link></li>)}</ul> : <EmptyState title="No active events"><span>Change filters or wait for new events.</span></EmptyState>}</section>
      <ShockMap events={events.filter((event) => event.source_type !== "market")} /><Opportunity event={activeEvent} />
      </>}
      <MarketPanel onSummary={setMarketSummary} />
      <Accuracy />
      <section className="panel ledger-preview" aria-labelledby="ledger-title"><div className="panel__head"><div><span className="eyebrow">Forecast ledger</span><h2 id="ledger-title">Prediction vs reality</h2></div><Link className="panel__link" href="/forecasts">Open forecasts <span aria-hidden="true">→</span></Link></div><div className="ledger-empty"><div className="ledger-icon"><Icon name="forecast" /></div><div><strong>Nothing has matured yet</strong><p className="muted">ECHO keeps forecasts separate from outcomes until the selected horizon closes.</p></div></div></section>
    </div>
  </div>;
}
