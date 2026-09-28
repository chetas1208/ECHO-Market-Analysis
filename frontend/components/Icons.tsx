import type { ReactNode } from "react";

/** Minimal 16px stroke icons. Decorative: always aria-hidden. */
const PATHS: Record<string, ReactNode> = {
  menu: <path d="M2 4h12M2 8h12M2 12h12" />,
  close: <path d="M3 3l10 10M13 3L3 13" />,
  search: <><circle cx="7" cy="7" r="4.5" /><path d="m10.5 10.5 3 3" /></>,
  pulse: <path d="M1.5 8h3l1.5-3 2.5 6 1.7-4h4.3" />,
  clock: <><circle cx="8" cy="8" r="5.5" /><path d="M8 4.8V8l2.2 1.4" /></>,
  user: <><circle cx="8" cy="5.5" r="2.5" /><path d="M3.5 14c.6-2.2 2-3.3 4.5-3.3s3.9 1.1 4.5 3.3" /></>,
  dashboard: <path d="M2 2h5v6H2zM9 2h5v3H9zM9 7h5v7H9zM2 10h5v4H2z" />,
  events: <path d="M1.5 8h2.5l1.5-4.5 3 9L10.5 8h4" />,
  graph: (
    <>
      <circle cx="3.5" cy="4" r="1.6" />
      <circle cx="12.5" cy="4" r="1.6" />
      <circle cx="8" cy="12.5" r="1.6" />
      <path d="M5 4.4h6M4.4 5.4l2.6 5.8M11.6 5.4L9 11.2" />
    </>
  ),
  forecast: <path d="M2 12l3.5-4 2.5 2L14 3.5M10.5 3.5H14V7" />,
  ledger: <path d="M3 2h10v12H3zM5.5 5.5h5M5.5 8h5M5.5 10.5h3" />,
  trade: <path d="M3 5h9.5M10 2.5L12.5 5 10 7.5M13 11H3.5M6 8.5L3.5 11 6 13.5" />,
  backtest: <path d="M2.5 8a5.5 5.5 0 1 0 1.7-4M2 2.5v3h3M8 5v3.2l2 1.3" />,
  analytics: <path d="M3 13V8M7 13V3M11 13V6M14 13H2" />,
  settings: (
    <>
      <circle cx="8" cy="8" r="2.2" />
      <path d="M8 1.5v2M8 12.5v2M1.5 8h2M12.5 8h2M3.4 3.4l1.4 1.4M11.2 11.2l1.4 1.4M12.6 3.4l-1.4 1.4M4.8 11.2l-1.4 1.4" />
    </>
  ),
};

export type IconName = keyof typeof PATHS;

export function Icon({ name }: { name: IconName }) {
  return (
    <svg
      className="icon"
      width="16"
      height="16"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.4"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {PATHS[name]}
    </svg>
  );
}

/** ECHO mark: a source dot with expanding arcs. */
export function EchoMark() {
  return (
    <svg className="mark" width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true" focusable="false">
      <circle cx="5" cy="10" r="1.8" fill="currentColor" />
      <path d="M9 5.5a6 6 0 0 1 0 9" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      <path d="M12.5 3a9.5 9.5 0 0 1 0 14" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" opacity=".55" />
      <path d="M16 1a13 13 0 0 1 0 18" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" opacity=".25" />
    </svg>
  );
}
