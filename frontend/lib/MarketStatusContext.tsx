"use client";

import { createContext, useCallback, useContext, useMemo, type ReactNode } from "react";
import type { DataMode, MarketStatus } from "@/types/market";
import { getMarketStatus } from "./marketApi";
import type { ApiError } from "./api";
import { usePolling } from "./usePolling";

export interface MarketStatusValue {
  /** Latest /market/status payload; null before the first success and while the backend is unreachable. */
  status: MarketStatus | null;
  /** Error from the most recent poll (cleared by the next success). */
  error: ApiError | null;
  /** True until the first poll settles. */
  loading: boolean;
  /** What the UI may claim about the data. OFFLINE unless the backend reports otherwise. */
  mode: DataMode;
}

const OFFLINE_VALUE: MarketStatusValue = { status: null, error: null, loading: true, mode: "OFFLINE" };

const MarketStatusContext = createContext<MarketStatusValue>(OFFLINE_VALUE);

/** Polls GET /market/status every 5 s (pauses while the tab is hidden) and shares the result. */
export function MarketStatusProvider({
  children,
  intervalMs = 5000,
}: {
  children: ReactNode;
  intervalMs?: number;
}) {
  const fetchStatus = useCallback((signal: AbortSignal) => getMarketStatus(signal), []);
  const { data, error, loading } = usePolling(fetchStatus, intervalMs);

  const value = useMemo<MarketStatusValue>(() => {
    // A failed poll means we cannot vouch for the last payload: never keep showing a stale LIVE.
    const status = error === null ? (data ?? null) : null;
    return { status, error, loading, mode: status?.mode ?? "OFFLINE" };
  }, [data, error, loading]);

  return <MarketStatusContext.Provider value={value}>{children}</MarketStatusContext.Provider>;
}

/** Current market data status. Outside a provider this reports OFFLINE (never LIVE). */
export function useMarketStatus(): MarketStatusValue {
  return useContext(MarketStatusContext);
}
