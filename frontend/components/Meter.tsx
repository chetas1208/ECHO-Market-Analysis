import { clamp, formatScore } from "@/lib/format";

/** Horizontal 0..1 meter with a numeric readout. */
export function Meter({
  label,
  abbr,
  value,
  tone = "accent",
}: {
  label: string;
  /** Short visible text for tight layouts; the full label stays the accessible name. */
  abbr?: string;
  value: number;
  tone?: "accent" | "neutral";
}) {
  const v = clamp(value, 0, 1);
  return (
    <div className="meter">
      <div className="meter__head">
        <span className="label" title={label}>
          {abbr ?? label}
        </span>
        <span className="mono meter__value">{formatScore(value)}</span>
      </div>
      <div
        className="meter__track"
        role="meter"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={1}
        aria-valuenow={v}
        aria-valuetext={formatScore(value)}
      >
        <div className={`meter__fill meter__fill--${tone}`} style={{ width: `${v * 100}%` }} />
      </div>
    </div>
  );
}
