import { formatUtc } from "@/lib/format";
import type { EchoEvent } from "@/types/event";
import { Badge } from "../Badge";
import styles from "./ShockCard.module.css";

const DASH = "—";
const SCORE_NOTE = "heuristic score, not a calibrated probability";

/** Finite number from a metadata value, else null (missing / NaN / Infinity / non-number). */
function num(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function str(value: unknown): string | null {
  return typeof value === "string" && value.trim() !== "" ? value : null;
}

/** Signed percent from a fractional return: 0.0123 -> "+1.23%". */
function pct(value: number | null): string {
  if (value === null) return DASH;
  const p = value * 100;
  return `${p > 0 ? "+" : ""}${p.toFixed(2)}%`;
}

/** Signed sigma: -3.2 -> "-3.2σ". */
function sigma(value: number | null): string {
  if (value === null) return DASH;
  return `${value > 0 ? "+" : ""}${value.toFixed(1)}σ`;
}

type Direction = "up" | "down" | null;

function directionOf(meta: Record<string, unknown>): Direction {
  const d = str(meta.direction)?.toLowerCase();
  if (d === "negative" || d === "down" || d === "downside") return "down";
  if (d === "positive" || d === "up" || d === "upside") return "up";
  for (const key of ["sector_residual", "market_residual", "return_5m"]) {
    const v = num(meta[key]);
    if (v !== null && v !== 0) return v < 0 ? "down" : "up";
  }
  return null;
}

/** Compact card for a canonical `market` / `market_shock` event. */
export function ShockCard({ event }: { event: EchoEvent }) {
  const meta = event.metadata ?? {};
  const symbol = event.companies[0] ?? str(meta.symbol) ?? DASH;
  const score = num(meta.shock_score);
  const dir = directionOf(meta);
  const noteId = `${event.id}-score-note`;

  const metrics: Array<[string, string]> = [
    ["5m return", pct(num(meta.return_5m))],
    ["Return", sigma(num(meta.return_z))],
    ["Volume", sigma(num(meta.volume_z))],
    ["Volatility", sigma(num(meta.volatility_z))],
    ["Sector resid.", pct(num(meta.sector_residual))],
    ["Market resid.", pct(num(meta.market_residual))],
    ["Sector bench.", str(meta.sector_benchmark) ?? DASH],
    ["Provider", str(meta.provider) ?? DASH],
  ];

  const cls = [
    styles.card,
    event.is_mock ? styles.mock : dir === "down" ? styles.down : dir === "up" ? styles.up : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <article className={cls} aria-label={`Market shock ${symbol}`} data-testid="shock-card">
      <header className={styles.head}>
        <div className={styles.badges}>
          <Badge tone="market">MARKET SHOCK</Badge>
          {event.is_mock ? (
            <Badge tone="mock" title="Replay/synthetic data, not a live market signal">
              REPLAY / MOCK
            </Badge>
          ) : null}
        </div>
        <span
          className={styles.score}
          title={SCORE_NOTE}
          aria-describedby={noteId}
          data-testid="shock-score"
        >
          {score === null ? `Shock score ${DASH}` : `Shock score ${score.toFixed(2)}`}
        </span>
        <span id={noteId} className="sr-only">
          {SCORE_NOTE}
        </span>
      </header>

      <div className={styles.titleRow}>
        <span
          className={`${styles.direction} ${dir === "down" ? styles.neg : dir === "up" ? styles.pos : ""}`}
          role="img"
          aria-label={dir === "down" ? "downside" : dir === "up" ? "upside" : "direction unknown"}
          data-testid="shock-direction"
        >
          {dir === "down" ? "▼" : dir === "up" ? "▲" : DASH}
        </span>
        <span className={styles.symbol}>{symbol}</span>
        <h3 className={styles.title}>{event.title}</h3>
      </div>

      <dl className={styles.metrics}>
        {metrics.map(([label, value]) => (
          <div key={label} className={styles.metric}>
            <dt>{label}</dt>
            <dd data-testid={`metric-${label}`}>{value}</dd>
          </div>
        ))}
      </dl>

      <time className={styles.time} dateTime={event.timestamp}>
        {formatUtc(event.timestamp)}
      </time>
    </article>
  );
}
