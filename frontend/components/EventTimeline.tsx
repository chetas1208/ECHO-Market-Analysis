import type { EventSource as EvidenceSource } from "@/types/world";
import styles from "./EventTimeline.module.css";

export type TimelineSource = Pick<EvidenceSource, "source_name" | "retrieved_at"> &
  Partial<Pick<EvidenceSource, "headline" | "published_at">>;

interface Row {
  key: string;
  publisher: string;
  headline: string | null;
  ms: number;
  unknownPublish: boolean;
  index: number;
}

function parseMs(value: string | null | undefined): number {
  if (typeof value !== "string" || !value) return Number.NaN;
  return Date.parse(value);
}

const pad = (n: number) => String(n).padStart(2, "0");

/** UTC HH:MM, prefixed with MM-DD when the day differs from the reference day. */
function formatUtc(ms: number, refMs: number): string {
  if (Number.isNaN(ms)) return "--:--";
  const d = new Date(ms);
  const hm = `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`;
  if (Number.isNaN(refMs)) return hm;
  const r = new Date(refMs);
  const sameDay =
    d.getUTCFullYear() === r.getUTCFullYear() &&
    d.getUTCMonth() === r.getUTCMonth() &&
    d.getUTCDate() === r.getUTCDate();
  return sameDay ? hm : `${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ${hm}`;
}

function isoTitle(ms: number): string | undefined {
  return Number.isNaN(ms) ? undefined : new Date(ms).toISOString();
}

/**
 * Compact vertical evidence timeline: event occurred, each source published (ascending),
 * then last updated. A source with no published_at is placed by retrieved_at and flagged.
 * All text is rendered as React text (external headlines are untrusted).
 */
export function EventTimeline({
  occurredAt,
  sources,
  revisions,
}: {
  occurredAt: string;
  sources: readonly TimelineSource[];
  revisions?: number;
}) {
  const occurredMs = parseMs(occurredAt);

  const rows: Row[] = sources.map((s, index) => {
    const pub = parseMs(s.published_at);
    const known = !Number.isNaN(pub);
    return {
      key: `${index}-${s.source_name}`,
      publisher: s.source_name,
      headline: s.headline ?? null,
      ms: known ? pub : parseMs(s.retrieved_at),
      unknownPublish: !known,
      index,
    };
  });
  rows.sort((a, b) => {
    const an = Number.isNaN(a.ms);
    const bn = Number.isNaN(b.ms);
    if (an !== bn) return an ? 1 : -1;
    return (an ? 0 : a.ms - b.ms) || a.index - b.index;
  });

  const retrieved = sources.map((s) => parseMs(s.retrieved_at)).filter((n) => !Number.isNaN(n));
  const lastUpdatedMs = retrieved.length ? Math.max(...retrieved) : Number.NaN;
  const showLast = revisions !== undefined || rows.length > 0;

  return (
    <ol className={styles.timeline} aria-label="Event timeline">
      <li className={`${styles.item} ${styles.occurred}`} data-kind="occurred">
        <time className={styles.time} dateTime={isoTitle(occurredMs)} title={isoTitle(occurredMs)}>
          {formatUtc(occurredMs, occurredMs)}
        </time>
        <span className={styles.body}>
          <span className={styles.label}>Event occurred</span>
        </span>
      </li>
      {rows.map((r) => (
        <li key={r.key} className={styles.item} data-kind="source">
          <time className={styles.time} dateTime={isoTitle(r.ms)} title={isoTitle(r.ms)}>
            {formatUtc(r.ms, occurredMs)}
          </time>
          <span className={styles.body}>
            <span className={styles.label}>
              <span className={styles.publisher}>{r.publisher}</span>
              {r.headline ? <span className={styles.headline}> {r.headline}</span> : null}
            </span>
            {r.unknownPublish && (
              <span className={styles.note}>
                unknown publish time (placed by retrieval time)
              </span>
            )}
          </span>
        </li>
      ))}
      {showLast && (
        <li className={`${styles.item} ${styles.updated}`} data-kind="updated">
          <time className={styles.time} dateTime={isoTitle(lastUpdatedMs)} title={isoTitle(lastUpdatedMs)}>
            {formatUtc(lastUpdatedMs, occurredMs)}
          </time>
          <span className={styles.body}>
            <span className={styles.label}>
              Last updated
              {revisions !== undefined ? ` (revision ${revisions})` : ""}
            </span>
          </span>
        </li>
      )}
    </ol>
  );
}
