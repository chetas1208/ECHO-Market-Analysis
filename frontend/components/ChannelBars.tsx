import { clamp, formatSigned, humanizeKey } from "@/lib/format";

/**
 * Economic channels as small diverging bars: negative extends left (red), positive right (green).
 * Values are signed exposures in [-1, 1]; sorted by magnitude.
 */
export function ChannelBars({ channels }: { channels: Record<string, number> }) {
  const rows = Object.entries(channels).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]));
  if (rows.length === 0) {
    return <p className="muted small">No economic channels mapped.</p>;
  }
  return (
    <ul className="channels" aria-label="Economic channels">
      {rows.map(([name, value]) => {
        const half = clamp(Math.abs(value), 0, 1) * 50;
        const sign = value > 0 ? "pos" : value < 0 ? "neg" : "zero";
        return (
          <li key={name} className="channels__row">
            <span className="channels__name" title={name}>
              {humanizeKey(name)}
            </span>
            <span className="channels__track" aria-hidden="true">
              <span className="channels__axis" />
              <span
                className={`channels__bar channels__bar--${sign}`}
                style={value < 0 ? { right: "50%", width: `${half}%` } : { left: "50%", width: `${half}%` }}
              />
            </span>
            <span className={`mono channels__value channels__value--${sign}`}>{formatSigned(value)}</span>
          </li>
        );
      })}
    </ul>
  );
}
