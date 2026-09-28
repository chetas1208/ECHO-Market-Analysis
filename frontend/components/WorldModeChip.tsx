import type { WorldMode } from "@/types/world";
import styles from "./WorldModeChip.module.css";

const MODES: Record<WorldMode, { text: string; label: string; cls: string | undefined }> = {
  LIVE: { text: "WORLD LIVE", label: "World feed: live", cls: styles.live },
  REPLAY: { text: "WORLD REPLAY", label: "World feed: replay (not live)", cls: styles.replay },
  OFFLINE: { text: "WORLD OFFLINE", label: "World feed: offline (no world events)", cls: styles.offline },
};

/** World-feed mode chip. "LIVE" appears only when mode is exactly LIVE; replay is amber, never green. */
export function WorldModeChip({ mode }: { mode: WorldMode }) {
  const m = MODES[mode] ?? MODES.OFFLINE;
  const key: WorldMode = MODES[mode] ? mode : "OFFLINE";
  return (
    <span
      role="status"
      aria-label={m.label}
      className={`${styles.chip} ${m.cls ?? ""}`}
      data-mode={key}
    >
      {key === "LIVE" && <span className={styles.dot} aria-hidden="true" />}
      {key === "REPLAY" && (
        <span className={styles.icon} aria-hidden="true">
          ◉
        </span>
      )}
      <span>{m.text}</span>
    </span>
  );
}
