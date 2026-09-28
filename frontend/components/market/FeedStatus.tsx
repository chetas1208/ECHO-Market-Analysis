"use client";

import { useEffect, useState } from "react";
import type { MarketStatus, ProviderHealth } from "@/types/market";
import styles from "./FeedStatus.module.css";

export const NO_PROVIDER_MESSAGE = "No market provider configured — set ECHO_MARKET_PROVIDER";

const pad = (n: number, w = 2) => String(n).padStart(w, "0");

/** "HH:MM:SS.mmm" in UTC; null when the input does not parse. */
export function formatUtcTimeMs(iso: string): string | null {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return (
    `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}` +
    `.${pad(d.getUTCMilliseconds(), 3)}`
  );
}

/** Compact age: "850ms", "12s", "4m 05s", "3h 02m", "2d". Negative skew clamps to 0. */
export function formatAge(iso: string, nowMs: number): string | null {
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return null;
  const ms = Math.max(0, nowMs - t);
  if (ms < 1000) return `${ms}ms`;
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${pad(s % 60)}s`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ${pad(Math.floor((s % 3600) / 60))}m`;
  return `${Math.floor(s / 86400)}d`;
}

function stateTone(state: string): string {
  switch (state) {
    case "CONNECTED":
      return styles.ok ?? "";
    case "DEGRADED":
    case "RECONNECTING":
    case "CONNECTING":
      return styles.warn ?? "";
    case "STALE":
    case "DISCONNECTED":
      return styles.bad ?? "";
    default:
      return styles.idle ?? ""; // UNCONFIGURED and anything unknown
  }
}

const fmtInt = (n: number) => n.toLocaleString("en-US");

function ProviderRow({
  p,
  activeProvider,
  nowMs,
}: {
  p: ProviderHealth;
  activeProvider: string | null;
  nowMs: number;
}) {
  const isActive = activeProvider !== null && p.provider === activeProvider;
  const standby =
    p.configured && p.state !== "UNCONFIGURED" && activeProvider !== null && !isActive;
  const ts = p.last_message_at ? formatUtcTimeMs(p.last_message_at) : null;
  const age = p.last_message_at ? formatAge(p.last_message_at, nowMs) : null;

  return (
    <li
      className={`${styles.row} ${isActive ? styles.rowActive : ""}`}
      data-testid={`provider-${p.provider}`}
      data-state={p.state}
    >
      <div className={styles.name}>
        <span>{p.provider}</span>
        <span className={`${styles.chip} ${stateTone(p.state)}`} data-testid="state-chip">
          {p.state}
        </span>
        {isActive ? <span className={`${styles.chip} ${styles.active}`}>ACTIVE</span> : null}
        {standby ? (
          <span
            className={`${styles.chip} ${styles.standby}`}
            title="Configured fallback; not the active provider"
          >
            STANDBY
          </span>
        ) : null}
      </div>

      <div className={styles.time}>
        <span className="label">Last msg</span>
        {ts ? (
          <>
            <span className={styles.ts} title={p.last_message_at ?? undefined}>
              {ts} UTC
            </span>
            {age ? <span className={styles.age}>{age} ago</span> : null}
          </>
        ) : (
          <span className={styles.age}>no messages yet</span>
        )}
      </div>

      <div className={styles.stats}>
        <span>
          msgs <b>{fmtInt(p.messages_received)}</b>
        </span>
        <span>
          malformed{" "}
          <b className={p.malformed_messages > 0 ? styles.warnValue : undefined}>
            {fmtInt(p.malformed_messages)}
          </b>
        </span>
        <span>
          reconnects{" "}
          <b className={p.reconnect_attempts > 0 ? styles.warnValue : undefined}>
            {fmtInt(p.reconnect_attempts)}
          </b>
        </span>
        <span>
          symbols <b>{fmtInt(p.subscribed_symbols.length)}</b>
        </span>
      </div>

      {p.last_error ? (
        <div className={styles.error} title="Last provider error">
          {p.last_error}
        </div>
      ) : null}
    </li>
  );
}

export interface FeedStatusProps {
  status: MarketStatus | null;
  loading?: boolean;
  error?: { message: string } | null;
  /** Epoch ms used for relative ages; defaults to Date.now() (override for tests). */
  now?: number;
}

/** Dense, read-only market feed health panel. Presentational: all data comes from props. */
export function FeedStatus({ status, loading = false, error = null, now }: FeedStatusProps) {
  const [tick, setTick] = useState(() => Date.now());
  useEffect(() => {
    if (now !== undefined) return;
    const id = setInterval(() => setTick(Date.now()), 1000);
    return () => clearInterval(id);
  }, [now]);
  const nowMs = now ?? tick;

  if (loading && !status) {
    return (
      <section className={styles.panel} aria-label="Feed status" aria-busy="true">
        <div role="status" aria-live="polite" data-testid="feed-loading">
          <span className="sr-only">Loading feed status…</span>
          <div aria-hidden="true" style={{ display: "grid", gap: 10 }}>
            <div className={styles.skeletonRow} style={{ width: "30%" }} />
            <div className={styles.skeletonRow} />
            <div className={styles.skeletonRow} style={{ width: "80%" }} />
          </div>
        </div>
      </section>
    );
  }

  if (error && !status) {
    return (
      <section className={styles.panel} aria-label="Feed status">
        <p className={styles.errorBox} role="alert" data-testid="feed-error">
          Could not load feed status: {error.message}
        </p>
      </section>
    );
  }

  if (!status || status.providers.length === 0) {
    return (
      <section className={styles.panel} aria-label="Feed status">
        <h3 className={styles.title}>Feed status</h3>
        <p className={styles.empty} data-testid="feed-offline">
          {NO_PROVIDER_MESSAGE}
        </p>
      </section>
    );
  }

  const { queue } = status;
  const nearFull = queue.capacity > 0 && queue.depth / queue.capacity >= 0.8;

  return (
    <section className={styles.panel} aria-label="Feed status" aria-busy={loading || undefined}>
      <div className={styles.head}>
        <h3 className={styles.title}>Feed status</h3>
        <div className={styles.meta}>
          <span>
            mode <b>{status.mode}</b>
          </span>
          <span>
            session <b data-testid="feed-session">{status.session}</b>
          </span>
          <span>
            active <b>{status.active_provider ?? "none"}</b>
          </span>
          <span>
            symbols <b>{fmtInt(status.subscribed_symbols.length)}</b>
          </span>
          <span data-testid="feed-queue">
            queue{" "}
            <b className={nearFull ? styles.warnValue : undefined}>
              {fmtInt(queue.depth)}/{fmtInt(queue.capacity)}
            </b>{" "}
            dropped{" "}
            <b className={queue.dropped > 0 ? styles.warnValue : undefined}>
              {fmtInt(queue.dropped)}
            </b>
          </span>
        </div>
      </div>

      {error ? (
        <p className={styles.errorBox} role="alert" data-testid="feed-error">
          Refresh failed, showing last known status: {error.message}
        </p>
      ) : null}

      <ul className={styles.list}>
        {status.providers.map((p) => (
          <ProviderRow key={p.provider} p={p} activeProvider={status.active_provider} nowMs={nowMs} />
        ))}
      </ul>

      {status.replay_finished ? (
        <p className={styles.note} data-testid="replay-finished">
          Replay finished — no further bars will be emitted.
        </p>
      ) : null}
    </section>
  );
}
