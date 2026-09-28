import { Badge, Chip } from "@/components/Badge";
import { ErrorState, type DisplayError } from "@/components/StateViews";
import styles from "./SourceEvidence.module.css";

/** One row of GET /api/v1/events/{id}/sources (docs/day3-contract.md). */
export interface SourceEvidenceItem {
  provider: string;
  source_name: string;
  source_group: string | null;
  source_url: string | null;
  headline: string | null;
  published_at: string | null;
  retrieved_at: string | null;
  is_independent: boolean;
  syndicated_from: string | null;
  reliability: number | null;
}

/** Return a normalized href only for http/https URLs; anything else is untrusted and not linkable. */
function safeUrl(raw: string | null | undefined): string | null {
  if (!raw) return null;
  try {
    const u = new URL(raw);
    return u.protocol === "http:" || u.protocol === "https:" ? u.href : null;
  } catch {
    return null;
  }
}

/** "2026-09-16 09:00 UTC" for valid timestamps; raw text (as text) otherwise; null when absent. */
function formatUtc(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return `${d.toISOString().slice(0, 16).replace("T", " ")} UTC`;
}

function SourceRow({ s }: { s: SourceEvidenceItem }) {
  const href = safeUrl(s.source_url);
  const published = formatUtc(s.published_at);
  const retrieved = formatUtc(s.retrieved_at);
  const isReplay = s.provider === "replay";
  return (
    <li className={styles.item} data-testid="source-item">
      <div className={styles.head}>
        <span className={styles.publisher}>{s.source_name}</span>
        {s.source_group ? <Chip mono>{s.source_group}</Chip> : null}
        {isReplay ? (
          <Badge tone="mock" title="Replayed fixture source, not a live provider">
            REPLAY
          </Badge>
        ) : (
          <Badge title="Data provider">{s.provider}</Badge>
        )}
      </div>
      {s.headline ? (
        <p className={styles.headline}>
          {href ? (
            <a href={href} rel="noopener noreferrer" target="_blank">
              {s.headline}
            </a>
          ) : (
            s.headline
          )}
        </p>
      ) : null}
      {!s.headline && href ? (
        <p className={styles.headline}>
          <a href={href} rel="noopener noreferrer" target="_blank">
            {href}
          </a>
        </p>
      ) : null}
      {!href && s.source_url ? (
        <p className={`${styles.headline} mono muted`} data-testid="source-url-text">
          {s.source_url}
        </p>
      ) : null}
      <p className={styles.times}>
        <span>published {published ?? "unavailable"}</span>
        <span>retrieved {retrieved ?? "unavailable"}</span>
      </p>
      <div className={styles.meta}>
        {s.is_independent ? (
          <Badge tone="neutral">
            <span className={styles.independent}>independent</span>
          </Badge>
        ) : (
          <Badge tone="neutral">
            <span className={styles.syndicated}>
              {s.syndicated_from ? `syndicated of ${s.syndicated_from}` : "syndicated"}
            </span>
          </Badge>
        )}
        <span>
          reliability (provider-supplied){" "}
          <span className={styles.reliability}>
            {typeof s.reliability === "number" ? s.reliability.toFixed(2) : "n/a"}
          </span>
        </span>
      </div>
    </li>
  );
}

function toDisplayError(error: DisplayError | string): DisplayError {
  return typeof error === "string" ? { message: error } : error;
}

export function SourceEvidence({
  sources,
  loading = false,
  error = null,
  total,
}: {
  sources: SourceEvidenceItem[];
  loading?: boolean;
  error?: DisplayError | string | null;
  total?: number;
}) {
  if (loading) {
    return (
      <div
        role="status"
        aria-live="polite"
        aria-busy="true"
        className={styles.root}
        data-testid="source-evidence-loading"
      >
        <span className="sr-only">Loading source evidence…</span>
        {[0, 1].map((i) => (
          <div key={i} className={styles.item} aria-hidden="true">
            <div className={styles.skeletonLine} style={{ width: "40%" }} />
            <div className={styles.skeletonLine} style={{ width: "85%" }} />
            <div className={styles.skeletonLine} style={{ width: "55%" }} />
          </div>
        ))}
      </div>
    );
  }

  if (error) {
    return <ErrorState error={toDisplayError(error)} title="Could not load source evidence" />;
  }

  if (sources.length === 0) {
    return (
      <div className="state-box" data-testid="source-evidence-empty">
        <p className="state-box__title">No source evidence recorded</p>
      </div>
    );
  }

  const count = total ?? sources.length;
  const independent = sources.filter((s) => s.is_independent).length;
  return (
    <div className={styles.root} data-testid="source-evidence">
      <p className={styles.summary} data-testid="source-summary">
        {`${count} ${count === 1 ? "source" : "sources"} · ${independent} independent`}
      </p>
      <ol className={styles.list} aria-label="Source evidence">
        {sources.map((s, i) => (
          <SourceRow key={`${s.provider}:${s.source_url ?? s.source_name}:${i}`} s={s} />
        ))}
      </ol>
    </div>
  );
}
