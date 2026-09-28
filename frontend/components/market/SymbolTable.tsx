import type { KeyboardEvent } from "react";
import type { MarketSymbolRow, SymbolState } from "@/types/market";
import { SYMBOL_STATE_LABEL, isShockState } from "@/types/market";
import styles from "./SymbolTable.module.css";

const EMPTY = "—";

function num(value: number | null | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function fmtPrice(v: number | null): string {
  return num(v) ? v.toFixed(2) : EMPTY;
}

function fmtSigned(v: number | null, digits: number, suffix = ""): string {
  if (!num(v)) return EMPTY;
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(digits)}${suffix}`;
}

/** Shock score is a heuristic in [0, 1] shown as a plain number, never a percent. */
function fmtScore(v: number | null): string {
  return num(v) ? v.toFixed(2) : EMPTY;
}

function absChange(row: MarketSymbolRow): number {
  return num(row.change_pct) ? Math.abs(row.change_pct) : -1;
}

/** Shocks first, then by |change| descending (missing change last), then symbol. */
export function compareRows(a: MarketSymbolRow, b: MarketSymbolRow): number {
  const shock = Number(isShockState(b.state)) - Number(isShockState(a.state));
  if (shock !== 0) return shock;
  const change = absChange(b) - absChange(a);
  if (change !== 0) return change;
  return a.symbol.localeCompare(b.symbol);
}

/** Equities sorted first; benchmarks are a separate, dimmer group at the bottom. */
export function sortRows(rows: readonly MarketSymbolRow[]): MarketSymbolRow[] {
  const equities = rows.filter((r) => r.role !== "benchmark").sort(compareRows);
  const benchmarks = rows.filter((r) => r.role === "benchmark").sort(compareRows);
  return [...equities, ...benchmarks];
}

const CHIP_CLASS: Record<SymbolState, string | undefined> = {
  NORMAL: styles.chipNormal,
  WATCH: styles.chipWatch,
  SHOCK: styles.chipShock,
  SEVERE: styles.chipSevere,
  WARMING_UP: styles.chipMuted,
  NO_DATA: styles.chipMuted,
};

export function SymbolTable({
  rows,
  selected,
  onSelect,
}: {
  rows: MarketSymbolRow[];
  selected?: string;
  onSelect?: (symbol: string) => void;
}) {
  const sorted = sortRows(rows);
  const firstBenchmark = sorted.findIndex((r) => r.role === "benchmark");

  const onKey = (e: KeyboardEvent<HTMLTableRowElement>, symbol: string) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onSelect?.(symbol);
    }
  };

  return (
    <div className={styles.wrap} tabIndex={0} role="region" aria-label="Symbols (scrollable)">
      <table className={styles.table}>
        <thead>
          <tr>
            <th scope="col" className={styles.left}>Symbol</th>
            <th scope="col" className={styles.left}>Group</th>
            <th scope="col">Price</th>
            <th scope="col">Chg %</th>
            <th scope="col">Vol z</th>
            <th scope="col" className={styles.left}>State</th>
            <th scope="col" title="Heuristic shock score in [0, 1]; not a probability">Score</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((row, i) => {
            const shock = isShockState(row.state);
            const benchmark = row.role === "benchmark";
            const cls = [
              styles.row,
              shock ? styles.shock : "",
              benchmark ? styles.benchmark : "",
              i === firstBenchmark ? styles.firstBenchmark : "",
              onSelect ? styles.clickable : "",
              selected === row.symbol ? styles.selected : "",
            ]
              .filter(Boolean)
              .join(" ");
            const chg = row.change_pct;
            const tone = !num(chg) || chg === 0 ? "" : chg > 0 ? styles.pos : styles.neg;
            const showArrow = row.direction != null && (shock || row.state === "WATCH");
            return (
              <tr
                key={row.symbol}
                className={cls}
                data-symbol={row.symbol}
                data-role={row.role}
                data-state={row.state}
                aria-current={selected === row.symbol ? "true" : undefined}
                tabIndex={onSelect ? 0 : undefined}
                onClick={onSelect ? () => onSelect(row.symbol) : undefined}
                onKeyDown={onSelect ? (e) => onKey(e, row.symbol) : undefined}
              >
                <th scope="row" className={`${styles.left} ${styles.sym}`}>
                  {row.symbol}
                  {benchmark ? <span className={styles.tag}>BM</span> : null}
                </th>
                <td className={styles.left}>{row.group}</td>
                <td className={styles.num}>{fmtPrice(row.price)}</td>
                <td className={`${styles.num} ${tone}`}>{fmtSigned(chg, 2, "%")}</td>
                <td className={styles.num}>{fmtSigned(row.volume_z, 1)}</td>
                <td className={styles.left}>
                  <span className={`${styles.chip} ${CHIP_CLASS[row.state] ?? ""}`}>
                    {SYMBOL_STATE_LABEL[row.state].toUpperCase()}
                  </span>
                  {showArrow ? (
                    <span
                      className={row.direction === "positive" ? styles.pos : styles.neg}
                      role="img"
                      aria-label={row.direction === "positive" ? "direction up" : "direction down"}
                    >
                      {row.direction === "positive" ? " ▲" : " ▼"}
                    </span>
                  ) : null}
                </td>
                <td className={styles.num} aria-label={num(row.shock_score) ? `score ${fmtScore(row.shock_score)}` : "score unavailable"}>
                  {fmtScore(row.shock_score)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
