/** Pure formatting helpers (no I/O). */

const pad = (n: number) => String(n).padStart(2, "0");

/** "2026-09-20 06:52:10 UTC" (returns the raw input if it does not parse). */
export function formatUtc(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return (
    `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ` +
    `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())} UTC`
  );
}

/** "3h ago", "in 5m", "just now". */
export function formatRelative(iso: string, nowMs: number = Date.now()): string {
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "";
  const diff = Math.round((nowMs - t) / 1000);
  const abs = Math.abs(diff);
  if (abs < 45) return "just now";
  const MIN = 60, HOUR = 3600, DAY = 86400;
  let text: string;
  if (abs < HOUR) text = `${Math.round(abs / MIN)}m`;
  else if (abs < DAY) text = `${Math.round(abs / HOUR)}h`;
  else if (abs < DAY * 30) text = `${Math.round(abs / DAY)}d`;
  else if (abs < DAY * 365) text = `${Math.round(abs / (DAY * 30))}mo`;
  else text = `${Math.round(abs / (DAY * 365))}y`;
  return diff >= 0 ? `${text} ago` : `in ${text}`;
}

/** Signed fixed-point: +0.77 / -0.82 / 0.00 */
export function formatSigned(value: number, digits = 2): string {
  const s = value.toFixed(digits);
  return value > 0 ? `+${s}` : s;
}

export function formatScore(value: number, digits = 2): string {
  return value.toFixed(digits);
}

export function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

/** "oil_supply" -> "oil supply" */
export function humanizeKey(key: string): string {
  return key.replace(/[_-]+/g, " ").trim();
}
