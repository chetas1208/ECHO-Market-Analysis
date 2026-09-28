"use client";

import { createContext, useCallback, useContext, useMemo, type ReactNode } from "react";
import type { WorldMode, WorldStatus } from "@/types/world";
import type { ApiError } from "./api";
import { usePolling } from "./usePolling";
import { getWorldStatus } from "./worldApi";

export const WORLD_STATUS_POLL_MS = 15_000;

export interface WorldStatusValue {
  /** Latest /world/status payload; null before the first success and while the backend is unreachable. */
  status: WorldStatus | null;
  /** Error from the most recent poll (cleared by the next success). */
  error: ApiError | null;
  /** True until the first poll settles (the UI shows no chip yet, rather than a guess). */
  loading: boolean;
  /** What the UI may claim about the world feed. OFFLINE unless the backend says otherwise. */
  mode: WorldMode;
}

const OFFLINE_VALUE: WorldStatusValue = { status: null, error: null, loading: false, mode: "OFFLINE" };

const WorldStatusContext = createContext<WorldStatusValue | null>(null);

/**
 * Resolve the mode the UI may show. Anything unrecognised is OFFLINE, and a replay provider can
 * never be reported as LIVE, even if the top-level mode field says so.
 */
export function resolveWorldMode(status: WorldStatus | null | undefined): WorldMode {
  const top = status?.mode;
  if (top !== "LIVE" && top !== "REPLAY" && top !== "OFFLINE") return "OFFLINE";
  const provider = status?.provider;
  if (top === "LIVE" && (provider?.mode === "REPLAY" || provider?.state === "REPLAY" || provider?.provider === "replay")) {
    return "REPLAY";
  }
  return top;
}

function Poller({ children, intervalMs }: { children: ReactNode; intervalMs: number }) {
  const fetchStatus = useCallback((signal: AbortSignal) => getWorldStatus(signal), []);
  const { data, error, loading } = usePolling(fetchStatus, intervalMs);

  const value = useMemo<WorldStatusValue>(() => {
    // A failed poll means we cannot vouch for the last payload: never keep showing a stale LIVE.
    const status = error === null ? (data ?? null) : null;
    return { status, error, loading, mode: resolveWorldMode(status) };
  }, [data, error, loading]);

  return <WorldStatusContext.Provider value={value}>{children}</WorldStatusContext.Provider>;
}

/**
 * Polls GET /world/status every 15 s (pauses while the tab is hidden) and shares the result.
 * Nested providers reuse the outermost one, so mounting it in a page and in a shell never double-polls.
 */
export function WorldStatusProvider({
  children,
  intervalMs = WORLD_STATUS_POLL_MS,
}: {
  children: ReactNode;
  intervalMs?: number;
}) {
  const parent = useContext(WorldStatusContext);
  if (parent) return <>{children}</>;
  return <Poller intervalMs={intervalMs}>{children}</Poller>;
}

/** Current world-feed status. Outside a provider this reports OFFLINE (never LIVE). */
export function useWorldStatus(): WorldStatusValue {
  return useContext(WorldStatusContext) ?? OFFLINE_VALUE;
}
