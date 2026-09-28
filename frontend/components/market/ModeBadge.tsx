import type { DataMode } from "@/types/market";
import styles from "./ModeBadge.module.css";

const MODES: Record<DataMode, { text: string; label: string; cls: string | undefined }> = {
  LIVE: { text: "LIVE", label: "Data mode: live (real-time market data)", cls: styles.live },
  REPLAY: {
    text: "REPLAY",
    label: "Data mode: replay (not live market data)",
    cls: styles.replay,
  },
  MOCK: { text: "MOCK", label: "Data mode: mock (synthetic data, not live market data)", cls: styles.mock },
  OFFLINE: { text: "OFFLINE", label: "Data mode: offline (no market data feed)", cls: styles.offline },
};

/** Pure presentational data-mode indicator. Each mode differs in text, shape and colour. */
export function ModeBadge({ mode, compact = false }: { mode: DataMode; compact?: boolean }) {
  const m = MODES[mode];
  const cls = [styles.badge, m.cls, compact ? styles.compact : ""].filter(Boolean).join(" ");
  return (
    <span role="status" aria-label={m.label} className={cls} data-mode={mode}>
      {mode === "LIVE" && <span className={styles.dot} aria-hidden="true" />}
      {mode === "REPLAY" && (
        <span className={styles.icon} aria-hidden="true">
          ◉
        </span>
      )}
      <span>{m.text}</span>
    </span>
  );
}
