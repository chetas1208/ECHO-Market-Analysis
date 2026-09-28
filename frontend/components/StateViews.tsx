import type { ReactNode } from "react";

export function LoadingState({ rows = 2 }: { rows?: number }) {
  return (
    <div role="status" aria-live="polite" aria-busy="true" className="state">
      <span className="sr-only">Loading events…</span>
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="skeleton" aria-hidden="true">
          <div className="skeleton__line skeleton__line--sm" />
          <div className="skeleton__line skeleton__line--lg" />
          <div className="skeleton__line" />
          <div className="skeleton__grid">
            <div className="skeleton__block" />
            <div className="skeleton__block" />
            <div className="skeleton__block" />
            <div className="skeleton__block" />
          </div>
        </div>
      ))}
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="state-box" data-testid="empty-state">
      <p className="state-box__title">{title}</p>
      {children ? <p className="muted">{children}</p> : null}
    </div>
  );
}

export interface DisplayError {
  message: string;
  code?: string;
  requestId?: string | null;
  status?: number;
}

export function ErrorState({
  error,
  onRetry,
  title = "Could not load events",
}: {
  error: DisplayError;
  onRetry?: () => void;
  title?: string;
}) {
  return (
    <div className="state-box state-box--error" role="alert" data-testid="error-state">
      <p className="state-box__title">{title}</p>
      <p>{error.message}</p>
      <dl className="kv mono">
        {error.code ? (
          <>
            <dt>code</dt>
            <dd>{error.code}</dd>
          </>
        ) : null}
        {error.status ? (
          <>
            <dt>http</dt>
            <dd>{error.status}</dd>
          </>
        ) : null}
        {error.requestId ? (
          <>
            <dt>request_id</dt>
            <dd>{error.requestId}</dd>
          </>
        ) : null}
      </dl>
      {onRetry ? (
        <button type="button" className="btn" onClick={onRetry}>
          Retry
        </button>
      ) : null}
    </div>
  );
}
