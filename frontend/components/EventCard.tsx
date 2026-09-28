import Link from "next/link";
import type { ReactNode } from "react";
import { clamp, formatRelative, formatScore, formatUtc } from "@/lib/format";
import type { EchoEvent } from "@/types/event";
import { Badge, Chip, MockBadge, SourceBadge } from "./Badge";
import { ChannelBars } from "./ChannelBars";
import styles from "./EventCard.module.css";
import { Meter } from "./Meter";
import { WorldScores } from "./ScoreRow";

export const MARKET_SHOCK_TYPE = "market_shock";

export function isMarketShock(event: EchoEvent): boolean {
  return event.source_type === "market" && event.event_type === MARKET_SHOCK_TYPE;
}

type Direction = "up" | "down" | null;

function shockDirection(metadata: Record<string, unknown>): Direction {
  const d = typeof metadata.direction === "string" ? metadata.direction.toLowerCase() : "";
  if (["positive", "up", "upside", "long"].includes(d)) return "up";
  if (["negative", "down", "downside", "short"].includes(d)) return "down";
  return null;
}

function shockScore(metadata: Record<string, unknown>): number | null {
  const v = metadata.shock_score;
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

/** One consistent source badge: WORLD / MARKET SHOCK / MARKET / FINANCIAL. */
function EventBadge({ event }: { event: EchoEvent }) {
  if (isMarketShock(event)) {
    return (
      <span className={styles.shockBadge}>
        <Badge tone="market" title="Abnormal market move detected from market data">
          MARKET SHOCK
        </Badge>
      </span>
    );
  }
  // world / market / financial: text is uppercased by the badge style.
  return <SourceBadge source={event.source_type} />;
}

function ShockLine({ event }: { event: EchoEvent }) {
  const dir = shockDirection(event.metadata);
  const arrow = dir === "up" ? "\u25B2" : dir === "down" ? "\u25BC" : "\u25C6";
  const label = dir === "up" ? "Upside move" : dir === "down" ? "Downside move" : "Direction unknown";
  return (
    <div className={styles.shockLine} data-testid="shock-line">
      <span
        className={`${styles.arrow} ${dir === "up" ? styles.up : dir === "down" ? styles.down : styles.flat}`}
        role="img"
        aria-label={label}
        title={label}
      >
        {arrow}
      </span>
      <ul className={styles.tickers} aria-label="Tickers">
        {event.companies.map((t) => (
          <Chip key={t} mono>
            {t}
          </Chip>
        ))}
      </ul>
    </div>
  );
}

/** Shock score in [0,1]: a composite abnormality score, NOT a probability or percent confidence. */
function ShockScore({ metadata }: { metadata: Record<string, unknown> }) {
  const score = shockScore(metadata);
  const text = score === null ? "Shock score \u2014" : `Shock score ${formatScore(score)}`;
  return (
    <div className="meter">
      <div className="meter__head">
        <span className="label" data-testid="shock-score">
          {text}
        </span>
      </div>
      <div
        className="meter__track"
        role="meter"
        aria-label="Shock score"
        aria-valuemin={0}
        aria-valuemax={1}
        aria-valuenow={score === null ? undefined : clamp(score, 0, 1)}
        aria-valuetext={text}
      >
        <div
          className="meter__fill meter__fill--accent"
          style={{ width: `${clamp(score ?? 0, 0, 1) * 100}%` }}
        />
      </div>
    </div>
  );
}

function ChipGroup({ label, items, mono }: { label: string; items: string[]; mono?: boolean }) {
  if (items.length === 0) return null;
  return (
    <div className="chipgroup">
      <span className="label">{label}</span>
      <ul className="chips">
        {items.map((item) => (
          <Chip key={item} mono={mono}>
            {item}
          </Chip>
        ))}
      </ul>
    </div>
  );
}

export function EventCard({
  event,
  now,
  detail = false,
  children,
}: {
  event: EchoEvent;
  /** Reference time (ms) for the relative timestamp. */
  now?: number;
  /** Detail mode: title is not a link. */
  detail?: boolean;
  children?: ReactNode;
}) {
  const rel = formatRelative(event.timestamp, now);
  const shock = isMarketShock(event);
  return (
    <article className={`card${event.is_mock ? " card--mock" : ""}`} aria-labelledby={`${event.id}-title`}>
      <header className="card__head">
        <div className="card__badges">
          <EventBadge event={event} />
          {event.is_mock ? <MockBadge /> : null}
          <span className="mono muted small" data-testid="event-type">
            {event.event_type}
          </span>
        </div>
        <span className="mono faint small card__id">{event.id}</span>
      </header>

      <h2 id={`${event.id}-title`} className="card__title">
        {detail ? (
          event.title
        ) : (
          <Link href={`/events/${encodeURIComponent(event.id)}`}>{event.title}</Link>
        )}
      </h2>

      <p className="mono small card__time">
        <time dateTime={event.timestamp}>{formatUtc(event.timestamp)}</time>
        {rel ? <span className="muted"> · {rel}</span> : null}
      </p>

      {shock ? <ShockLine event={event} /> : null}

      {event.summary ? <p className="card__summary">{event.summary}</p> : null}

      {shock ? (
        <div className="card__meters">
          <Meter label="Severity" value={event.severity} />
          <ShockScore metadata={event.metadata} />
          <Meter label="Novelty" value={event.novelty} tone="neutral" />
          <Meter label="Corroboration" abbr="Corrob." value={event.corroboration} tone="neutral" />
        </div>
      ) : event.source_type === "world" ? (
        <WorldScores event={event} />
      ) : (
        <div className="card__meters">
          <Meter label="Severity" value={event.severity} />
          <Meter label="Confidence" value={event.confidence} tone="neutral" />
          <Meter label="Novelty" value={event.novelty} tone="neutral" />
          <Meter label="Corroboration" abbr="Corrob." value={event.corroboration} tone="neutral" />
        </div>
      )}

      {shock && Object.keys(event.economic_channels).length === 0 ? null : (
        <section className="card__section" aria-label="Economic channels">
          <h3 className="label">Economic channels</h3>
          <ChannelBars channels={event.economic_channels} />
        </section>
      )}

      <div className="card__tags">
        <ChipGroup label="Entities" items={event.entities} />
        {shock ? null : <ChipGroup label="Companies" items={event.companies} mono />}
        <ChipGroup label="Locations" items={event.locations} />
      </div>

      {children}
    </article>
  );
}
