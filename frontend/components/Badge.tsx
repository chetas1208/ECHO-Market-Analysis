import type { ReactNode } from "react";
import type { SourceType } from "@/types/event";

type Tone = "neutral" | "accent" | "mock" | "world" | "market" | "financial";

export function Badge({
  tone = "neutral",
  title,
  children,
}: {
  tone?: Tone;
  title?: string;
  children: ReactNode;
}) {
  return (
    <span className={`badge badge--${tone}`} title={title}>
      {children}
    </span>
  );
}

export function SourceBadge({ source }: { source: SourceType }) {
  return <Badge tone={source}>{source}</Badge>;
}

/** Shown on every event that is fixture/mock data rather than a real ingested signal. */
export function MockBadge() {
  return (
    <Badge tone="mock" title="Synthetic fixture event, not a real-world signal">
      MOCK / FIXTURE
    </Badge>
  );
}

export function Chip({ children, mono = false }: { children: ReactNode; mono?: boolean }) {
  return <li className={mono ? "chip chip--mono" : "chip"}>{children}</li>;
}
