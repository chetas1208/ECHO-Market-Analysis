"use client";

import { useEffect } from "react";
import Link from "next/link";

export default function GlobalError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    console.error("ECHO page boundary", error);
  }, [error]);

  return (
    <main className="error-page" role="alert">
      <span className="eyebrow">ECHO / degraded</span>
      <h1>This workspace is temporarily unavailable.</h1>
      <p>The replay and research paths remain available when the API is healthy again.</p>
      <div className="error-page__actions">
        <button className="btn btn--primary" type="button" onClick={reset}>Retry workspace</button>
        <Link className="btn" href="/events">Open event feed</Link>
      </div>
    </main>
  );
}
