"use client";

import { useCallback } from "react";
import { getOperationalStatus } from "@/lib/api";
import { useApiResource } from "@/lib/useApiResource";
import { ErrorState, LoadingState } from "./StateViews";
import { PageHeader } from "./PageHeader";
import styles from "./OpsWorkspace.module.css";

export function OpsWorkspace() {
  const fetchStatus = useCallback((signal: AbortSignal) => getOperationalStatus(signal), []);
  const { state, reload } = useApiResource(fetchStatus);

  if (state.status === "loading") return <LoadingState rows={3} />;
  if (state.status === "error") {
    return <ErrorState error={state.error} onRetry={reload} title="Operational status unavailable" />;
  }

  const data = state.data;
  return (
    <div className={styles.workspace} data-testid="ops-workspace">
      <PageHeader
        title="Operations"
        meta="SECONDARY VIEW · READ-ONLY DIAGNOSTICS"
        actions={
          <div className={styles.summary}>
            <span className={styles.state} data-state={data.status}>
              <span className={styles.dot} aria-hidden="true" />{data.status}
            </span>
            <span className={styles.time}>{new Date(data.checked_at).toISOString()}</span>
          </div>
        }
      />
      <section className={styles.grid} aria-label="Service dependencies">
        {Object.entries(data.dependencies).map(([name, dependency]) => (
          <article className={styles.card} key={name}>
            <h2>{name}</h2>
            <div className={styles.dependency} data-state={dependency.state}>
              <span className={styles.dot} aria-hidden="true" />
              <span>{dependency.state}</span>
              <span className={styles.status}>{dependency.status}</span>
            </div>
            <p className={styles.detail}>{dependency.detail}</p>
          </article>
        ))}
      </section>
    </div>
  );
}
