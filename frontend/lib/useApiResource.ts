"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError, isAbortError } from "./api";

export type ResourceState<T> =
  | { status: "loading" }
  | { status: "success"; data: T }
  | { status: "error"; error: ApiError };

/**
 * Runs `fetcher` on mount (and whenever `fetcher` identity changes), aborting the in-flight
 * request on unmount. `reload` re-runs it. `fetcher` must be memoized by the caller.
 */
export function useApiResource<T>(fetcher: (signal: AbortSignal) => Promise<T>, enabled = true) {
  const [state, setState] = useState<ResourceState<T>>({ status: "loading" });
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    if (!enabled) {
      return;
    }
    const controller = new AbortController();
    fetcher(controller.signal)
      .then((data) => setState({ status: "success", data }))
      .catch((err: unknown) => {
        if (isAbortError(err) || controller.signal.aborted) return;
        setState({
          status: "error",
          error:
            err instanceof ApiError
              ? err
              : new ApiError({
                  message: err instanceof Error ? err.message : "Unexpected error.",
                  status: 0,
                  code: "unknown_error",
                }),
        });
      });
    return () => controller.abort();
  }, [enabled, fetcher, nonce]);

  const reload = useCallback(() => {
    setState({ status: "loading" });
    setNonce((n) => n + 1);
  }, []);

  return { state, reload };
}
