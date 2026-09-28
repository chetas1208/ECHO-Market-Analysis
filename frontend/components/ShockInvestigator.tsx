"use client";

import { useState } from "react";
import { getEventMarketImpact, getMarketClusters, investigateMarketShock } from "@/lib/api";
import type { CauseInvestigation, ClusterShockList, MarketImpact } from "@/types/cause";
import type { EchoEvent } from "@/types/event";
import styles from "./ShockInvestigator.module.css";

function number(value: unknown): string {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(2) : "—";
}

function isMarketShock(event: EchoEvent): boolean {
  return event.source_type === "market" && event.event_type === "market_shock";
}

function CausePanel({ event }: { event: EchoEvent }) {
  const [result, setResult] = useState<CauseInvestigation | null>(null);
  const [clusters, setClusters] = useState<ClusterShockList | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function investigate() {
    setLoading(true);
    setError(null);
    try {
      const [investigation, clusterResult] = await Promise.all([
        investigateMarketShock(event.id),
        getMarketClusters(),
      ]);
      setResult(investigation);
      setClusters(clusterResult);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Cause investigation unavailable");
    } finally {
      setLoading(false);
    }
  }

  const statusClass = result
    ? styles[result.status.toLowerCase() as "identified" | "ambiguous" | "unknown"]
    : "";
  const cluster = clusters?.items[0];
  return <section className={styles.section} aria-labelledby="cause-investigator-title" data-testid="cause-investigator">
    <div className={styles.header}>
      <div>
        <span className="label">market shock</span>
        <h2 className={styles.title} id="cause-investigator-title">Shock Investigator</h2>
        <p className={styles.subtle}>Stored evidence, timing, graph paths, and peer response are ranked deterministically.</p>
      </div>
      <button className={styles.button} type="button" onClick={investigate} disabled={loading}>
        {loading ? "Investigating…" : "Investigate causes"}
      </button>
    </div>
    {error ? <p className={styles.status} role="alert">{error}</p> : null}
    {result ? <div className={styles.status}>
      <strong className={statusClass}>{result.status}</strong>
      <span> · evidence score, not causal probability · snapshot {result.graph_snapshot_id}</span>
      {result.status === "UNKNOWN" ? <p>No candidate event passed the configured evidence threshold.</p> : null}
      {result.status === "AMBIGUOUS" ? <p>Top candidates are too close to claim one explanation.</p> : null}
      <div className={styles.candidates}>
        {result.candidates.length ? result.candidates.map((candidate, index) => <details className={styles.candidate} key={candidate.event_id} open={index === 0}>
          <summary><div className={styles.candidateHead}><span>{index + 1}. {candidate.title}</span><span className={styles.score}>{candidate.score.toFixed(2)}</span></div></summary>
          <dl className={styles.facts}>
            <div><dt>time</dt><dd>{candidate.temporal_score.toFixed(2)}</dd></div>
            <div><dt>economic</dt><dd>{candidate.economic_score.toFixed(2)}</dd></div>
            <div><dt>graph</dt><dd>{candidate.graph_score.toFixed(2)}</dd></div>
            <div><dt>market</dt><dd>{candidate.market_score.toFixed(2)}</dd></div>
            <div><dt>source</dt><dd>{candidate.source_score.toFixed(2)}</dd></div>
            <div><dt>direction</dt><dd>{candidate.directional_consistency > 0 ? "agree" : candidate.directional_consistency < 0 ? "oppose" : "unknown"}</dd></div>
          </dl>
          <pre className={styles.evidence}>{JSON.stringify(candidate.evidence, null, 2)}</pre>
        </details>) : <p className={styles.empty}>No candidate events were visible at the declared cutoff.</p>}
      </div>
      {cluster ? <div className={styles.status}><strong>Related cluster</strong><p>{cluster.cluster_key} · {cluster.direction} · {cluster.abnormal_count}/{cluster.member_count} members · strength {cluster.strength.toFixed(2)}</p></div> : null}
    </div> : null}
  </section>;
}

function ImpactPanel({ event }: { event: EchoEvent }) {
  const [result, setResult] = useState<MarketImpact | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function analyze() {
    setLoading(true);
    setError(null);
    try { setResult(await getEventMarketImpact(event.id)); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Market impact unavailable"); }
    finally { setLoading(false); }
  }
  return <section className={styles.section} aria-labelledby="market-impact-title" data-testid="market-impact">
    <div className={styles.header}>
      <div><span className="label">world event</span><h2 className={styles.title} id="market-impact-title">Observed market response</h2><p className={styles.subtle}>Exposure is compared with normalized residual movement; this is not a forecast.</p></div>
      <button className={styles.button} type="button" onClick={analyze} disabled={loading}>{loading ? "Analyzing…" : "Analyze response"}</button>
    </div>
    {error ? <p className={styles.status} role="alert">{error}</p> : null}
    {result ? <div className={styles.impactList}>{result.market_confirmation_unavailable ? <p className={styles.empty}>Market confirmation is unavailable at this cutoff.</p> : null}{result.companies.map((company) => <div className={styles.impact} key={company.symbol}><div className={styles.impactHead}><span className={styles.impactSymbol}>{company.symbol}</span><span className={company.exposure >= 0 ? styles.positive : styles.negative}>{number(company.exposure)} · {company.response_state}</span></div><p className={styles.subtle}>confidence {number(company.confidence)} · residual {number(company.actual_residual_z)}σ</p></div>)}</div> : null}
  </section>;
}

export function ShockInvestigator({ event }: { event: EchoEvent }) {
  return isMarketShock(event) ? <CausePanel event={event} /> : <ImpactPanel event={event} />;
}
