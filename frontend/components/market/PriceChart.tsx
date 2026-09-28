"use client";

import { useRef } from "react";
import type { KeyboardEvent } from "react";
import { INTERVALS } from "@/types/market";
import type { Bar, Interval } from "@/types/market";
import styles from "./PriceChart.module.css";

export interface PriceChartMarker {
  /** ISO-8601 UTC timestamp of the event. */
  timestamp: string;
  label: string;
  direction?: "positive" | "negative";
}

export interface PriceChartProps {
  bars: Bar[];
  interval: Interval;
  onIntervalChange: (interval: Interval) => void;
  markers?: PriceChartMarker[];
  /** viewBox height; width scales responsively via viewBox + CSS. */
  height?: number;
}

const VB_W = 640;
const PAD = { top: 16, right: 64, bottom: 24, left: 8 };
const MAX_TICKS = 5;

interface Pt {
  t: number;
  x: number;
  y: number;
  close: number;
}

/** UTC HH:MM. */
export function formatUtcTime(ms: number): string {
  const d = new Date(ms);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(d.getUTCHours())}:${p(d.getUTCMinutes())}`;
}

function formatPrice(v: number): string {
  return v.toFixed(Math.abs(v) < 1 ? 4 : 2);
}

function num(v: number): string {
  return String(Math.round(v * 100) / 100);
}

/** Index of the point whose time is closest to `t` (points ascending, non-empty). */
function nearestIndex(pts: Pt[], t: number): number {
  let best = 0;
  let bestD = Infinity;
  for (let i = 0; i < pts.length; i++) {
    const d = Math.abs(pts[i]!.t - t);
    if (d < bestD) {
      bestD = d;
      best = i;
    }
  }
  return best;
}

function IntervalSelector({
  interval,
  onChange,
}: {
  interval: Interval;
  onChange: (i: Interval) => void;
}) {
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});
  const onKeyDown = (e: KeyboardEvent<HTMLButtonElement>, idx: number) => {
    let next = idx;
    if (e.key === "ArrowRight" || e.key === "ArrowDown") next = (idx + 1) % INTERVALS.length;
    else if (e.key === "ArrowLeft" || e.key === "ArrowUp")
      next = (idx - 1 + INTERVALS.length) % INTERVALS.length;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = INTERVALS.length - 1;
    else return;
    e.preventDefault();
    const target = INTERVALS[next];
    if (!target) return;
    onChange(target);
    refs.current[target]?.focus();
  };
  return (
    <div role="radiogroup" aria-label="Bar interval" className={styles.segmented}>
      {INTERVALS.map((iv, idx) => {
        const active = iv === interval;
        return (
          <button
            key={iv}
            ref={(el) => {
              refs.current[iv] = el;
            }}
            type="button"
            role="radio"
            aria-checked={active}
            tabIndex={active ? 0 : -1}
            className={active ? `${styles.seg} ${styles.segActive}` : styles.seg}
            onClick={() => onChange(iv)}
            onKeyDown={(e) => onKeyDown(e, idx)}
          >
            {iv}
          </button>
        );
      })}
    </div>
  );
}

/** Dependency-free inline-SVG close-price chart with event markers. */
export function PriceChart({
  bars,
  interval,
  onIntervalChange,
  markers = [],
  height = 260,
}: PriceChartProps) {
  const VB_H = height;
  const plotW = VB_W - PAD.left - PAD.right;
  const plotH = Math.max(VB_H - PAD.top - PAD.bottom, 1);

  const clean = bars
    .map((b) => ({ t: Date.parse(b.timestamp), close: b.close }))
    .filter((b) => Number.isFinite(b.t) && Number.isFinite(b.close))
    .sort((a, b) => a.t - b.t);

  const header = <IntervalSelector interval={interval} onChange={onIntervalChange} />;

  if (clean.length === 0) {
    return (
      <div className={styles.wrap} data-testid="price-chart">
        <div className={styles.toolbar}>{header}</div>
        <div className={styles.empty} role="status">
          No bars yet
        </div>
      </div>
    );
  }

  const closes = clean.map((b) => b.close);
  const lo = Math.min(...closes);
  const hi = Math.max(...closes);
  const flat = hi === lo;
  // Flat series: synthesize a symmetric range so nothing divides by zero.
  const yLo = flat ? lo - (Math.abs(lo) * 0.001 || 0.5) : lo;
  const yHi = flat ? hi + (Math.abs(hi) * 0.001 || 0.5) : hi;
  const span = yHi - yLo;
  const first0 = clean[0];
  const last0 = clean[clean.length - 1];
  if (!first0 || !last0) return null;
  const t0 = first0.t;
  const t1 = last0.t;
  const tSpan = t1 - t0;

  const xOf = (t: number) => (tSpan > 0 ? PAD.left + ((t - t0) / tSpan) * plotW : PAD.left + plotW / 2);
  const yOf = (v: number) => PAD.top + (1 - (v - yLo) / span) * plotH;

  const pts: Pt[] = clean.map((b) => ({ t: b.t, close: b.close, x: xOf(b.t), y: yOf(b.close) }));
  const first = pts[0];
  const last = pts[pts.length - 1];
  if (!first || !last) return null;
  const baseY = PAD.top + plotH;
  const linePath = pts.map((p, i) => `${i === 0 ? "M" : "L"}${num(p.x)} ${num(p.y)}`).join(" ");
  const areaPath = `${linePath} L${num(last.x)} ${num(baseY)} L${num(first.x)} ${num(baseY)} Z`;

  const tickCount = Math.min(MAX_TICKS, pts.length);
  const tickIdx = Array.from(
    new Set(
      Array.from({ length: tickCount }, (_, k) =>
        tickCount === 1 ? 0 : Math.round((k * (pts.length - 1)) / (tickCount - 1)),
      ),
    ),
  );

  const up = last.close >= first.close;
  const tagH = 16;
  const tagY = Math.min(Math.max(last.y - tagH / 2, PAD.top - 4), baseY - tagH + 4);

  const marks = markers
    .map((m, i) => ({ m, i, t: Date.parse(m.timestamp) }))
    .filter((x) => Number.isFinite(x.t))
    .map(({ m, i, t }) => {
      const idx = nearestIndex(pts, t);
      const p = pts[idx] ?? last;
      return { m, i, idx, x: p.x, y: p.y };
    });

  const desc = `${interval} close price, ${pts.length} bar${pts.length === 1 ? "" : "s"}, ${formatUtcTime(t0)} to ${formatUtcTime(t1)} UTC, last ${formatPrice(last.close)}`;

  return (
    <div className={styles.wrap} data-testid="price-chart">
      <div className={styles.toolbar}>{header}</div>
      <svg
        className={styles.svg}
        viewBox={`0 0 ${VB_W} ${VB_H}`}
        preserveAspectRatio="xMidYMid meet"
        role="img"
        aria-label={desc}
      >
        {/* grid at min / max */}
        <line className={styles.grid} x1={PAD.left} x2={PAD.left + plotW} y1={PAD.top} y2={PAD.top} />
        <line className={styles.grid} x1={PAD.left} x2={PAD.left + plotW} y1={baseY} y2={baseY} />

        <path
          className={`${styles.area} ${up ? styles.up : styles.down}`}
          d={areaPath}
          data-testid="price-area"
        />
        {pts.length > 1 ? (
          <path
            className={`${styles.line} ${up ? styles.up : styles.down}`}
            d={linePath}
            data-testid="price-line"
            data-points={pts.length}
          />
        ) : (
          <circle
            className={`${styles.dot} ${up ? styles.up : styles.down}`}
            cx={last.x}
            cy={last.y}
            r={3}
            data-testid="price-line"
            data-points={1}
          />
        )}

        {/* axis labels: min / max */}
        <text className={styles.axis} x={PAD.left + plotW + 6} y={PAD.top + 3} data-testid="axis-max">
          {formatPrice(hi)}
        </text>
        <text className={styles.axis} x={PAD.left + plotW + 6} y={baseY} data-testid="axis-min">
          {formatPrice(lo)}
        </text>

        {/* time axis */}
        {tickIdx.map((i) => {
          const p = pts[i];
          if (!p) return null;
          const anchor = i === 0 && pts.length > 1 ? "start" : i === pts.length - 1 && pts.length > 1 ? "end" : "middle";
          return (
            <text
              key={i}
              className={styles.axis}
              x={p.x}
              y={VB_H - 6}
              textAnchor={anchor}
              data-testid="time-tick"
            >
              {formatUtcTime(p.t)}
            </text>
          );
        })}

        {/* event markers */}
        {marks.map(({ m, i, idx, x, y }) => {
          const tone = m.direction === "positive" ? styles.pos : m.direction === "negative" ? styles.neg : styles.neutral;
          const glyph = m.direction === "positive" ? "▲ " : m.direction === "negative" ? "▼ " : "";
          const flip = x > PAD.left + plotW * 0.65;
          return (
            <g key={`${m.timestamp}-${i}`} className={`${styles.marker} ${tone}`} data-testid="chart-marker" data-bar-index={idx}>
              <line x1={x} x2={x} y1={PAD.top} y2={baseY} className={styles.markerLine} />
              <circle cx={x} cy={y} r={3.5} className={styles.markerDot} />
              <text
                x={flip ? x - 5 : x + 5}
                y={PAD.top + 10 + (i % 3) * 12}
                textAnchor={flip ? "end" : "start"}
                className={styles.markerLabel}
              >
                {glyph}
                {m.label}
              </text>
            </g>
          );
        })}

        {/* last-price tag */}
        <g className={`${styles.tag} ${up ? styles.up : styles.down}`} data-testid="last-price">
          <line className={styles.tagLine} x1={last.x} x2={PAD.left + plotW} y1={last.y} y2={last.y} />
          <rect x={PAD.left + plotW + 2} y={tagY} width={PAD.right - 4} height={tagH} rx={2} className={styles.tagBox} />
          <text x={PAD.left + plotW + 2 + (PAD.right - 4) / 2} y={tagY + 11.5} textAnchor="middle" className={styles.tagText}>
            {formatPrice(last.close)}
          </text>
        </g>
      </svg>
    </div>
  );
}
