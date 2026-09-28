import type { ReactNode } from "react";
import { clamp, formatScore } from "@/lib/format";
import type { EchoEvent } from "@/types/event";
import styles from "./ScoreRow.module.css";

export type SeverityBucket = "HIGH" | "ELEVATED" | "MODERATE" | "LOW";

/** Local copy of the backend bucket thresholds: HIGH >= 0.70, ELEVATED >= 0.50, MODERATE >= 0.30, else LOW. */
export function severityBucket(value: number): SeverityBucket {
  if (value >= 0.7) return "HIGH";
  if (value >= 0.5) return "ELEVATED";
  if (value >= 0.3) return "MODERATE";
  return "LOW";
}

export const CONFIDENCE_TOOLTIP = "Heuristic interpretation confidence — not a calibrated probability";

const BUCKET_CLASS: Record<SeverityBucket, string | undefined> = {
  HIGH: styles.high,
  ELEVATED: styles.elevated,
  MODERATE: styles.moderate,
  LOW: styles.low,
};

/** Non-breaking additions to the event JSON (day 3 contract); absent on older payloads. */
type WorldCountFields = { source_count?: unknown; independent_source_count?: unknown };

function count(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : null;
}

function plural(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** One 0..1 meter whose readout is caller-defined (never a percentage). */
function ScoreMeter({
  label,
  visibleLabel,
  value,
  valueText,
  readout,
  tone = "neutral",
  title,
  testId,
}: {
  /** Accessible name of the meter. */
  label: string;
  visibleLabel?: string;
  value: number;
  valueText: string;
  readout: ReactNode;
  tone?: "accent" | "neutral";
  title?: string;
  testId?: string;
}) {
  const v = clamp(value, 0, 1);
  return (
    <div className="meter" data-testid={testId}>
      <div className="meter__head">
        <span className="label" title={title ?? label}>
          {visibleLabel ?? label}
        </span>
        <span className={`mono meter__value ${styles.readout}`}>{readout}</span>
      </div>
      <div
        className="meter__track"
        role="meter"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={1}
        aria-valuenow={v}
        aria-valuetext={valueText}
      >
        <div className={`meter__fill meter__fill--${tone}`} style={{ width: `${v * 100}%` }} />
      </div>
    </div>
  );
}

/**
 * Truthful score labels for WORLD events. Scores are heuristic, so they are shown as a
 * bucket / count / plain 0.00 number and never as a percentage or probability.
 */
export function WorldScores({ event }: { event: EchoEvent }) {
  const counts = event as EchoEvent & WorldCountFields;
  const independent = count(counts.independent_source_count);
  const sources = count(counts.source_count);
  const location = event.locations[0];
  const bucket = severityBucket(event.severity);

  return (
    <div data-testid="world-scores">
      <div className="card__meters">
        <ScoreMeter
          label="Severity"
          value={event.severity}
          valueText={`${bucket} ${formatScore(event.severity)}`}
          tone="accent"
          readout={
            <>
              <span className={`${styles.bucket} ${BUCKET_CLASS[bucket]}`} data-testid="severity-bucket">
                {bucket}
              </span>
              <span>{formatScore(event.severity)}</span>
            </>
          }
        />
        <ScoreMeter
          label="Confidence"
          visibleLabel="Confidence score"
          title={CONFIDENCE_TOOLTIP}
          value={event.confidence}
          valueText={`score ${formatScore(event.confidence)}`}
          readout={formatScore(event.confidence)}
        />
        <ScoreMeter
          label="Novelty"
          value={event.novelty}
          valueText={`score ${formatScore(event.novelty)}`}
          readout={formatScore(event.novelty)}
        />
        <ScoreMeter
          label="Corroboration"
          value={event.corroboration}
          valueText={
            independent === null
              ? `score ${formatScore(event.corroboration)}`
              : `${plural(independent, "independent source", "independent sources")}, score ${formatScore(event.corroboration)}`
          }
          testId="corroboration"
          readout={
            independent === null
              ? `score ${formatScore(event.corroboration)}`
              : plural(independent, "independent source", "independent sources")
          }
        />
      </div>
      {location || sources !== null ? (
        <p className={`small muted ${styles.meta}`} data-testid="world-meta">
          {location ? <span data-testid="world-location">{location}</span> : null}
          {sources !== null ? <span data-testid="world-source-count">{plural(sources, "source", "sources")}</span> : null}
        </p>
      ) : null}
    </div>
  );
}
