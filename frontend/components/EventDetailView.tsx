"use client";

import Link from "next/link";
import { useMemo, type ReactNode } from "react";
import { getEvent } from "@/lib/api";
import { useApiResource } from "@/lib/useApiResource";
import { formatRelative, formatScore, formatUtc } from "@/lib/format";
import { getEventSources } from "@/lib/worldApi";
import type { EchoEvent } from "@/types/event";
import { Chip, MockBadge, SourceBadge } from "./Badge";
import { ChannelList } from "./ChannelList";
import { EventCard } from "./EventCard";
import { EventTimeline } from "./EventTimeline";
import { PageHeader } from "./PageHeader";
import { WorldScores } from "./ScoreRow";
import { SourceEvidence } from "./SourceEvidence";
import { ErrorState, LoadingState } from "./StateViews";
import styles from "./EventDetail.module.css";

function JsonBlock({ label, value }: { label: string; value: unknown }) {
  return (
    <section className="card__section">
      <h3 className="label">{label}</h3>
      <pre className="json mono">{JSON.stringify(value, null, 2)}</pre>
    </section>
  );
}

const DASH = "\u2014";

/** Metric rows for a market_shock event; keys are the metadata keys emitted by the shock detector. */
const SHOCK_METRIC_KEYS = [
  "shock_score",
  "return_5m",
  "return_z",
  "volume_z",
  "volatility_z",
  "sector_residual",
  "market_residual",
  "provider",
  "components",
] as const;

function formatMetric(value: unknown): string {
  if (typeof value === "number") return Number.isFinite(value) ? String(Number(value.toPrecision(4))) : DASH;
  if (typeof value === "string") return value || DASH;
  if (value && typeof value === "object" && !Array.isArray(value)) {
    const parts = Object.entries(value as Record<string, unknown>).map(([k, v]) => `${k} ${formatMetric(v)}`);
    return parts.length ? parts.join(" \u00B7 ") : DASH;
  }
  return DASH;
}

function isMarketShockEvent(event: EchoEvent): boolean {
  return event.source_type === "market" && event.event_type === "market_shock";
}

/** Shock metrics as a small table. The score is a heuristic, never shown as a percent or probability. */
function ShockMetrics({ metadata }: { metadata: Record<string, unknown> }) {
  return (
    <section className="card__section" aria-label="Shock metrics" data-testid="shock-metrics">
      <h3 className="label">Shock metrics</h3>
      <p className="muted small" data-testid="shock-metrics-note">
        Heuristic score {"\u2014"} not a calibrated probability
      </p>
      <table className={`mono small ${styles.metrics}`}>
        <tbody>
          {SHOCK_METRIC_KEYS.map((key) => (
            <tr key={key}>
              <th scope="row">{key}</th>
              <td>{formatMetric(metadata[key])}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function ChipGroup({ label, items, mono }: { label: string; items: string[]; mono?: boolean }) {
  if (items.length === 0) return null;
  return (
    <div className="chipgroup">
      <span className="label">{label}</span>
      <ul className="chips" aria-label={label}>
        {items.map((item) => (
          <Chip key={item} mono={mono}>
            {item}
          </Chip>
        ))}
      </ul>
    </div>
  );
}

/** metadata.channel_evidence -> { channel: [rule, ...] }; anything malformed is dropped (never invented). */
function channelEvidence(metadata: Record<string, unknown>): Record<string, string[]> | undefined {
  const raw = metadata.channel_evidence;
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return undefined;
  const out: Record<string, string[]> = {};
  for (const [channel, rules] of Object.entries(raw as Record<string, unknown>)) {
    if (!Array.isArray(rules)) continue;
    const strings = rules.filter((r): r is string => typeof r === "string" && r.length > 0);
    if (strings.length) out[channel] = strings;
  }
  return Object.keys(out).length ? out : undefined;
}

function plural(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** What each heuristic score means. Text only; nothing here is a recommendation. */
function ScoreSemantics() {
  return (
    <details className={styles.semantics} data-testid="score-semantics">
      <summary>Score semantics</summary>
      <dl className={styles.semanticsList}>
        <dt>Severity</dt>
        <dd>Economic significance if the event is true. It is not sentiment and not a forecast.</dd>
        <dt>Corroboration</dt>
        <dd>Support from independent sources. A heuristic count-and-diversity score; syndicated copies add less.</dd>
        <dt>Confidence</dt>
        <dd>How sure the system is of its interpretation of the event. Not a calibrated probability.</dd>
        <dt>Channels</dt>
        <dd>Directional pressure from {"\u22121"} to +1 on an economic channel. Not an expected price move.</dd>
      </dl>
    </details>
  );
}

/** Detail body for a WORLD event: scores, entities, timeline, channels + rules, and source evidence. */
function WorldEventDetail({ event, children }: { event: EchoEvent; children?: ReactNode }) {
  const fetchSources = useMemo(() => (signal: AbortSignal) => getEventSources(event.id, signal), [event.id]);
  const { state: sources, reload } = useApiResource(fetchSources);
  const rel = formatRelative(event.timestamp);
  const items = sources.status === "success" && Array.isArray(sources.data.items) ? sources.data.items : [];
  const total = sources.status === "success" ? sources.data.total : undefined;

  const independent =
    typeof event.independent_source_count === "number"
      ? event.independent_source_count
      : sources.status === "success" && items.length > 0
        ? items.filter((s) => s.is_independent).length
        : null;
  const corroboration =
    independent === null
      ? `Corroboration: independent source count unavailable (score ${formatScore(event.corroboration)})`
      : `Corroboration: ${plural(independent, "independent source", "independent sources")} (score ${formatScore(event.corroboration)})`;

  return (
    <article className={`card${event.is_mock ? " card--mock" : ""}`} aria-labelledby={`${event.id}-title`} data-testid="world-detail">
      <header className="card__head">
        <div className="card__badges">
          <SourceBadge source="world" />
          {event.is_mock ? <MockBadge /> : null}
          <span className="mono muted small" data-testid="event-type">
            {event.event_type}
          </span>
        </div>
        <span className="mono faint small card__id">{event.id}</span>
      </header>

      <h2 id={`${event.id}-title`} className="card__title">
        {event.title}
      </h2>
      <p className="mono small card__time">
        <time dateTime={event.timestamp}>{formatUtc(event.timestamp)}</time>
        {rel ? <span className="muted"> · {rel}</span> : null}
      </p>

      {event.summary ? (
        <p className="card__summary" data-testid="world-summary">
          {event.summary}
        </p>
      ) : null}

      <WorldScores event={event} />
      <p className={`small ${styles.corroboration}`} data-testid="corroboration-line">
        {corroboration}
      </p>

      <div className="card__tags">
        <ChipGroup label="Locations" items={event.locations} />
        <ChipGroup label="Entities" items={event.entities} />
        <ChipGroup label="Companies" items={event.companies} mono />
      </div>

      <section className="card__section" aria-label="Timeline">
        <h3 className="label">Timeline</h3>
        <EventTimeline occurredAt={event.timestamp} sources={items} revisions={event.revision} />
      </section>

      <section className="card__section" aria-label="Economic channels">
        <h3 className="label">Economic channels</h3>
        <ChannelList channels={event.economic_channels} evidence={channelEvidence(event.metadata)} />
      </section>

      <section className="card__section" aria-label="Source evidence">
        <h3 className="label">Source evidence</h3>
        <SourceEvidence
          sources={items}
          total={total}
          loading={sources.status === "loading"}
          error={sources.status === "error" ? sources.error : null}
        />
        {sources.status === "error" ? (
          <div>
            <button type="button" className="btn" onClick={reload}>
              Retry sources
            </button>
          </div>
        ) : null}
      </section>

      <ScoreSemantics />

      {children}
    </article>
  );
}

/** Detail view for one event: WORLD events get the evidence layout, others reuse EventCard + raw refs/metadata. */
export function EventDetailView({ id }: { id: string }) {
  const fetcher = useMemo(() => (signal: AbortSignal) => getEvent(id, signal), [id]);
  const { state, reload } = useApiResource(fetcher);

  return (
    <div className={styles.page}>
      <PageHeader
        title="Event Detail"
        meta={<Link href="/events">&larr; Events</Link>}
      />
      {state.status === "loading" ? <LoadingState rows={1} /> : null}
      {state.status === "error" ? (
        <ErrorState title="Could not load event" error={state.error} onRetry={reload} />
      ) : null}
      {state.status === "success" && state.data.source_type === "world" ? (
        <WorldEventDetail event={state.data}>
          <dl className="kv mono card__section">
            <dt>created_at</dt>
            <dd>{formatUtc(state.data.created_at)}</dd>
            <dt>ingested_at</dt>
            <dd>{formatUtc(state.data.ingested_at)}</dd>
          </dl>
          <JsonBlock label="Source refs" value={state.data.source_refs} />
          <JsonBlock label="Metadata" value={state.data.metadata} />
        </WorldEventDetail>
      ) : null}
      {state.status === "success" && state.data.source_type !== "world" ? (
        <EventCard event={state.data} detail>
          <dl className="kv mono card__section">
            <dt>created_at</dt>
            <dd>{formatUtc(state.data.created_at)}</dd>
            <dt>ingested_at</dt>
            <dd>{formatUtc(state.data.ingested_at)}</dd>
          </dl>
          {isMarketShockEvent(state.data) ? <ShockMetrics metadata={state.data.metadata} /> : null}
          <JsonBlock label="Source refs" value={state.data.source_refs} />
          <JsonBlock label="Metadata" value={state.data.metadata} />
        </EventCard>
      ) : null}
    </div>
  );
}
