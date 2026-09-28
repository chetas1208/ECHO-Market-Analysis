"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, isAbortError } from "./api";

export interface PollingResult<T> {
  /** Last successfully fetched value (kept when a later poll fails). */
  data: T | undefined;
  /** Error from the most recent poll; cleared by the next success. */
  error: ApiError | null;
  /** True until the first poll settles (success or error). */
  loading: boolean;
  lastUpdated: Date | null;
  /** Poll now (no-op if a request is already in flight). */
  refresh: () => void;
}

function toApiError(err: unknown): ApiError {
  if (err instanceof ApiError) return err;
  return new ApiError({
    message: err instanceof Error ? err.message : "Unexpected error.",
    status: 0,
    code: "unknown_error",
  });
}

/**
 * Polls `fetcher` every `intervalMs` (default 5 s). Sequential (next poll is scheduled only after
 * the previous settles, so requests never overlap), paused while `document.hidden` (resumes with
 * an immediate poll), aborts in-flight on unmount. `fetcher` need not be memoized.
 */
export function usePolling<T>(
  fetcher: (signal: AbortSignal) => Promise<T>,
  intervalMs = 5000,
): PollingResult<T> {
  const [data, setData] = useState<T | undefined>(undefined);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const fetcherRef = useRef(fetcher);
  useEffect(() => {
    fetcherRef.current = fetcher;
  });
  const pollRef = useRef<() => void>(() => {});

  useEffect(() => {
    let disposed = false;
    let controller: AbortController | null = null;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const clearTimer = () => {
      if (timer !== null) clearTimeout(timer);
      timer = null;
    };
    const schedule = () => {
      clearTimer();
      if (disposed || document.hidden) return;
      timer = setTimeout(poll, intervalMs);
    };

    function poll() {
      clearTimer();
      if (disposed || controller !== null) return; // no overlapping requests
      const c = new AbortController();
      controller = c;
      let pending: Promise<T>;
      try {
        pending = fetcherRef.current(c.signal);
      } catch (err) {
        pending = Promise.reject(err);
      }
      pending
        .then((value) => {
          if (disposed || c.signal.aborted) return;
          setData(value);
          setError(null);
          setLastUpdated(new Date());
        })
        .catch((err: unknown) => {
          if (disposed || c.signal.aborted || isAbortError(err)) return;
          setError(toApiError(err));
        })
        .finally(() => {
          if (controller === c) controller = null;
          if (disposed) return;
          setLoading(false);
          schedule();
        });
    }

    const onVisibility = () => {
      if (document.hidden) clearTimer();
      else poll();
    };

    pollRef.current = poll;
    document.addEventListener("visibilitychange", onVisibility);
    if (!document.hidden) poll();

    return () => {
      disposed = true;
      clearTimer();
      document.removeEventListener("visibilitychange", onVisibility);
      controller?.abort();
      controller = null;
    };
  }, [intervalMs]);

  const refresh = useCallback(() => pollRef.current(), []);

  return { data, error, loading, lastUpdated, refresh };
}
