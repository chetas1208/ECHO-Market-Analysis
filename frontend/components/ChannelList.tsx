"use client";

import { useId, useState } from "react";
import styles from "./ChannelList.module.css";

export interface ChannelListProps {
  /** Signed directional pressure per channel, nominally in [-1, 1]. */
  channels: Record<string, number>;
  /** Optional rule names per channel, e.g. { oil_supply: ["class:shipping_disruption"] }. */
  evidence?: Record<string, string[]>;
}

/** "oil_supply" -> "Oil supply" */
export function channelLabel(key: string): string {
  const s = key.replace(/[_-]+/g, " ").trim();
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/** Display value: finite numbers clamped to [-1, 1]; anything else (NaN, ±Infinity handled) -> 0. */
function displayValue(v: unknown): number {
  if (typeof v !== "number" || Number.isNaN(v)) return 0;
  return Math.min(1, Math.max(-1, v));
}

function fmt(v: number): string {
  const s = v.toFixed(2);
  // avoid "-0.00"
  if (Number(s) === 0) return "0.00";
  return v > 0 ? `+${s}` : s;
}

function Row({ name, value, rules }: { name: string; value: number; rules: string[] }) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const label = channelLabel(name);
  const sign = value > 0 ? "pos" : value < 0 ? "neg" : "zero";
  const half = Math.abs(value) * 50;
  const valueClass = sign === "pos" ? styles.valuePos : sign === "neg" ? styles.valueNeg : styles.valueZero;
  return (
    <li className={styles.row} data-testid="channel-row">
      <div className={styles.main}>
        <span className={styles.name} title={name}>
          {label}
        </span>
        <span className={styles.track} aria-hidden="true">
          <span className={styles.axis} />
          {sign !== "zero" && (
            <span
              className={`${styles.bar} ${sign === "pos" ? styles.pos : styles.neg}`}
              style={value < 0 ? { right: "50%", width: `${half}%` } : { left: "50%", width: `${half}%` }}
            />
          )}
        </span>
        <span className={`mono ${styles.value} ${valueClass}`}>{fmt(value)}</span>
        {rules.length > 0 ? (
          <button
            type="button"
            className={styles.toggle}
            aria-expanded={open}
            aria-controls={panelId}
            aria-label={`Evidence for ${label}`}
            onClick={() => setOpen((o) => !o)}
          >
            {open ? "Hide" : "Evidence"} ({rules.length})
          </button>
        ) : (
          <span className={styles.spacer} aria-hidden="true" />
        )}
      </div>
      {rules.length > 0 && open && (
        <ul id={panelId} className={styles.evidence} aria-label={`${label} evidence rules`}>
          {rules.map((r, i) => (
            <li key={`${r}-${i}`} className={styles.rule}>
              {r}
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

/**
 * Economic channels: human label, signed value, diverging bar (negative left / red, positive right / green),
 * sorted by magnitude, with optional expandable evidence rules. An empty set is a valid result (abstention).
 * All text is rendered as React text; nothing is interpreted as HTML.
 */
export function ChannelList({ channels, evidence }: ChannelListProps) {
  const rows = Object.entries(channels ?? {})
    .map(([name, raw]) => ({ name, value: displayValue(raw) }))
    .sort((a, b) => Math.abs(b.value) - Math.abs(a.value) || a.name.localeCompare(b.name));

  if (rows.length === 0) {
    return <p className={styles.empty}>No economic channels identified</p>;
  }
  return (
    <div>
      <ul className={styles.list} aria-label="Economic channels">
        {rows.map(({ name, value }) => (
          <Row key={name} name={name} value={value} rules={evidence?.[name] ?? []} />
        ))}
      </ul>
      <p className={styles.legend}>Directional pressure (−1 … +1) — not an expected price move</p>
    </div>
  );
}
