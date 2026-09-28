"use client";

import { useEffect, useMemo, useState } from "react";
import {
  createForecastVintage,
  getForecastEvaluation,
  getForecastingStatus,
  listForecastVintages,
  previewForecast,
  simulateForecast,
} from "@/lib/api";
import type { ForecastHorizonKey, ForecastPreview, ForecastingStatus } from "@/types/forecast";
import type { ForecastEvaluation, ForecastVintage, SimulatedTrade } from "@/types/ledger";
import { PageHeader } from "./PageHeader";
import styles from "./ForecastWorkspace.module.css";

const HORIZONS: ForecastHorizonKey[] = ["1D", "2D", "5D", "10D", "20D"];

function percent(value: number | null | undefined): string {
  return value === null || value === undefined || !Number.isFinite(value) ? "—" : `${(value * 100).toFixed(2)}%`;
}

function dateTime(value: string): string {
  return new Date(value).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function ForecastCard({ result, onCreate }: { result: ForecastPreview; onCreate: () => void }) {
  const [selected, setSelected] = useState<ForecastHorizonKey>(result.recommended_horizon ?? "5D");
  const horizon = result.horizons[selected];
  const values = [horizon?.q10, horizon?.q90].filter((value): value is number => typeof value === "number");
  const min = values.length ? Math.min(...values, 0) : -1;
  const max = values.length ? Math.max(...values, 0) : 1;
  const scale = Math.max(max - min, 1e-9);
  const left = horizon?.q10 === undefined || horizon.q10 === null ? 0 : ((horizon.q10 - min) / scale) * 100;
  const width = horizon?.q10 === undefined || horizon.q90 === undefined || horizon.q10 === null || horizon.q90 === null ? 0 : ((horizon.q90 - horizon.q10) / scale) * 100;
  return <section className={styles.panel} aria-labelledby="forecast-result-title">
    <span className={styles.label}>frozen candidate</span>
    <h2 className={styles.title} id="forecast-result-title">{result.symbol} · expected abnormal return</h2>
    <p className={styles.subtle}>Issued {dateTime(result.issued_at)} · cutoff {dateTime(result.data_cutoff_at)}. Values are CAR, not raw-price predictions.</p>
    <div className={styles.horizons} role="tablist" aria-label="Forecast horizons">
      {HORIZONS.map((item) => <div className={`${styles.horizon} ${selected === item ? styles.horizonSelected : ""}`} key={item}><button className={styles.horizonButton} type="button" role="tab" aria-selected={selected === item} onClick={() => setSelected(item)}>{item}</button></div>)}
    </div>
    {horizon ? <>
      <div className={styles.metric}><span>q10 · q50 · q90</span>{percent(horizon.q10)} · {percent(horizon.q50)} · {percent(horizon.q90)}</div>
      <div className={styles.band} aria-label="Forecast interval band"><div className={styles.bandFill} style={{ left: `${left}%`, width: `${width}%` }} /></div>
      <div className={styles.boundary}><span>historical cutoff</span><span>frozen forecast · {selected}</span></div>
      <div className={styles.metric}><span>probability positive abnormal return</span>{percent(horizon.probability_positive)}</div>
      <div className={styles.metric}><span>recommended horizon</span>{result.recommended_horizon ?? "Unavailable"}</div>
    </> : <p className={styles.subtle}>No horizon is available at this cutoff.</p>}
    <div className={styles.ledgerAction}><button className={styles.button} type="button" onClick={onCreate} disabled={result.model_status !== "READY"}>Create immutable vintage</button></div>
    <details className={styles.diagnostics}><summary>Model diagnostics</summary><pre>{JSON.stringify({ model_version: result.model_version, model_artifact_hash: result.model_artifact_hash, feature_version: result.feature_version, feature_hash: result.feature_hash, graph_snapshot_id: result.graph_snapshot_id, information_half_life: result.information_half_life, ...result.diagnostics }, null, 2)}</pre></details>
  </section>;
}

function LedgerDetail({ vintage, evaluation, trade, onSimulate }: { vintage: ForecastVintage; evaluation: ForecastEvaluation[]; trade: SimulatedTrade | null; onSimulate: () => void }) {
  return <section className={styles.panel} aria-labelledby="vintage-detail-title">
    <span className={styles.label}>immutable prediction vintage</span>
    <h2 className={styles.title} id="vintage-detail-title">{vintage.symbol} · {dateTime(vintage.issued_at)}</h2>
    <p className={styles.subtle}>The forecast values below are loaded from the ledger. New actual observations can extend reality, but cannot rewrite these points.</p>
    <dl className={styles.metadata}>
      <div><dt>event</dt><dd>{vintage.event_id ?? "—"}</dd></div>
      <div><dt>model</dt><dd>{vintage.model_version}</dd></div>
      <div><dt>artifact hash</dt><dd>{vintage.model_artifact_hash ?? "unavailable"}</dd></div>
      <div><dt>graph snapshot</dt><dd>{vintage.graph_snapshot_id ?? "—"}</dd></div>
      <div><dt>feature hash</dt><dd>{vintage.feature_hash ?? "—"}</dd></div>
      <div><dt>content hash</dt><dd>{vintage.content_hash ?? "—"}</dd></div>
    </dl>
    <div className={styles.ledger}>
      <table className={styles.ledgerTable}><thead><tr><th>Horizon</th><th>q50</th><th>P+</th><th>Actual</th><th>Error</th><th>Status</th></tr></thead><tbody>
        {vintage.horizons.map((point) => { const item = evaluation.find((row) => row.horizon === point.horizon); return <tr key={point.horizon}><td>{point.horizon}</td><td>{percent(point.q50)}</td><td>{percent(point.probability_positive)}</td><td>{percent(item?.actual_abnormal_return)}</td><td>{percent(item?.absolute_error)}</td><td className={item?.status === "COMPLETE" ? styles.statusComplete : styles.statusPending}>{item?.status ?? "PENDING"}</td></tr>; })}
      </tbody></table>
    </div>
    <div className={styles.ledgerAction}><button className={styles.button} type="button" onClick={onSimulate}>Run deterministic simulation</button>{trade ? <span className={styles.statusChip}>{trade.side} · {trade.status} · net {percent(trade.return_on_allocated_capital)}</span> : null}</div>
  </section>;
}

export function ForecastWorkspace() {
  const [eventId, setEventId] = useState("");
  const [symbol, setSymbol] = useState("NVDA");
  const [status, setStatus] = useState<ForecastingStatus | null>(null);
  const [result, setResult] = useState<ForecastPreview | null>(null);
  const [vintages, setVintages] = useState<ForecastVintage[]>([]);
  const [selectedVintage, setSelectedVintage] = useState<ForecastVintage | null>(null);
  const [evaluation, setEvaluation] = useState<ForecastEvaluation[]>([]);
  const [trade, setTrade] = useState<SimulatedTrade | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const refreshLedger = () => listForecastVintages().then((body) => setVintages(body.items)).catch(() => setVintages([]));
  useEffect(() => { getForecastingStatus().then(setStatus).catch(() => setStatus(null)); refreshLedger(); }, []);
  useEffect(() => { if (selectedVintage) getForecastEvaluation(selectedVintage.id).then((body) => setEvaluation(body.items)).catch(() => setEvaluation([])); }, [selectedVintage]);
  const statusLabel = useMemo(() => status?.artifact_available ? `READY · ${status.backend}` : "FORECAST_UNAVAILABLE", [status]);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!eventId.trim() || !symbol.trim()) { setMessage("Event ID and symbol are required."); return; }
    setLoading(true); setMessage(null); setResult(null);
    try { setResult(await previewForecast({ event_id: eventId.trim(), symbol: symbol.trim().toUpperCase() })); }
    catch (error) { setMessage(error instanceof Error ? error.message : "Forecast preview unavailable"); }
    finally { setLoading(false); }
  }

  async function createVintage() {
    if (!result) return;
    try { const created = await createForecastVintage({ preview: result, config_hash: "0a12a4f032384e664e898b49bbd791d17849a44fdd19798ff116ea08dc2e7c98", idempotency_key: `${result.event_id}:${result.symbol}:${result.issued_at}` }); setSelectedVintage(created); setMessage("Immutable forecast vintage created."); await refreshLedger(); }
    catch (error) { setMessage(error instanceof Error ? error.message : "Could not create immutable vintage"); }
  }

  async function simulate() {
    if (!selectedVintage) return;
    try { setTrade(await simulateForecast(selectedVintage.id, { horizon: selectedVintage.recommended_horizon, mode: "HISTORICAL_REPLAY" })); }
    catch (error) { setMessage(error instanceof Error ? error.message : "Simulation unavailable"); }
  }

  return <div className={styles.page}>
    <PageHeader title="Forecasts" meta="Prediction ledger · Day 7" />
    <div className={styles.grid}>
      <section className={styles.panel} aria-labelledby="forecast-context-title">
        <span className={styles.label}>event-conditioned forecast</span>
        <h2 className={styles.title} id="forecast-context-title">Preview a forecast vintage</h2>
        <p className={styles.subtle}>Preview is ephemeral until explicitly frozen into the append-only ledger. The simulator is paper-only and never sends broker orders.</p>
        <form className={styles.form} onSubmit={submit}>
          <label className={styles.field}>Event ID<input className={styles.input} value={eventId} onChange={(e) => setEventId(e.target.value)} placeholder="evt_…" /></label>
          <label className={styles.field}>Company symbol<input className={styles.input} value={symbol} onChange={(e) => setSymbol(e.target.value)} /></label>
          <button className={styles.button} type="submit" disabled={loading}>{loading ? "Building forecast…" : "Preview forecast"}</button>
        </form>
        <div className={styles.status}>engine status: <strong className={status?.artifact_available ? styles.ready : styles.unavailable}>{statusLabel}</strong></div>
        {message ? <p className={styles.error} role="status">{message}</p> : null}
        {result?.model_status === "FORECAST_UNAVAILABLE" ? <div className={styles.status}><strong className={styles.unavailable}>FORECAST_UNAVAILABLE</strong><p>{result.unavailable_reason}</p></div> : null}
      </section>
      {result?.model_status === "READY" ? <ForecastCard result={result} onCreate={createVintage} /> : <section className={styles.panel}><span className={styles.label}>distribution view</span><h2 className={styles.title}>No forecast selected</h2><p className={styles.subtle}>A successful backend response will render q10/q50/q90 bands, probability, and diagnostics. No production values are mocked.</p></section>}
    </div>
    <section className={`${styles.panel} ${styles.ledger}`} aria-labelledby="ledger-title"><span className={styles.label}>prediction ledger</span><h2 className={styles.title} id="ledger-title">Frozen forecast vintages</h2>{vintages.length ? <table className={styles.ledgerTable}><thead><tr><th>Issued</th><th>Symbol</th><th>Event</th><th>Recommended</th><th>q50</th><th>State</th></tr></thead><tbody>{vintages.map((vintage) => { const point = vintage.horizons.find((item) => item.horizon === vintage.recommended_horizon) ?? vintage.horizons[0]; return <tr className={styles.ledgerRow} key={vintage.id}><td><button type="button" onClick={() => { setSelectedVintage(vintage); setTrade(null); }}>{dateTime(vintage.issued_at)}</button></td><td>{vintage.symbol}</td><td>{vintage.event_id ?? "—"}</td><td>{vintage.recommended_horizon ?? "—"}</td><td>{percent(point?.q50)}</td><td>{vintage.ood_status ?? "UNKNOWN"}</td></tr>; })}</tbody></table> : <p className={styles.empty}>No immutable vintages yet. Preview a forecast and freeze it when you want historical evidence.</p>}</section>
    {selectedVintage ? <div className={styles.detailGrid}><LedgerDetail vintage={selectedVintage} evaluation={evaluation} trade={trade} onSimulate={simulate} /><section className={styles.panel}><span className={styles.label}>provenance</span><h2 className={styles.title}>Forecast vs reality</h2><p className={styles.subtle}>The issuance cutoff is the boundary. Forecast points remain frozen; actual observations and evaluation status append over time.</p><div className={styles.status}>integrity: content hash verification is available from the API<br />model: {selectedVintage.model_version}<br />graph: {selectedVintage.graph_snapshot_id ?? "not attached"}<br />cutoff: {dateTime(selectedVintage.data_cutoff_at)}</div></section></div> : null}
  </div>;
}
