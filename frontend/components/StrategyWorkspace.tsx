"use client";

import { useEffect, useMemo, useState } from "react";
import type { CSSProperties } from "react";
import { getBacktestResearch, getBacktestTrades, getExecutionStatus, getPaperPositions, listBacktests } from "@/lib/api";
import type { BacktestRun, BacktestTrade } from "@/types/backtest";
import type { ExecutionStatus, PaperPosition } from "@/types/execution";
import { PageHeader } from "./PageHeader";
import styles from "./StrategyWorkspace.module.css";

const percent = (value: number | null, digits = 2) => value === null ? "—" : `${(value * 100).toFixed(digits)}%`;
const ratio = (value: number | null) => value === null ? "—" : value.toFixed(2);

export function StrategyWorkspace() {
  const [run, setRun] = useState<BacktestRun | null>(null);
  const [trades, setTrades] = useState<BacktestTrade[]>([]);
  const [execution, setExecution] = useState<ExecutionStatus | null>(null);
  const [positions, setPositions] = useState<PaperPosition[]>([]);
  const [research, setResearch] = useState<Awaited<ReturnType<typeof getBacktestResearch>> | null>(null);
  const [copied, setCopied] = useState(false);
  const [state, setState] = useState<"loading" | "ready" | "empty" | "error">("loading");

  useEffect(() => {
    const controller = new AbortController();
    void listBacktests(controller.signal).then(async (response) => {
      const latest = response.items[response.items.length - 1];
      if (!latest) { setState("empty"); return; }
      setRun(latest);
      setTrades(await getBacktestTrades(latest.run_id, controller.signal));
      setState("ready");
    }).catch((error: unknown) => {
      if (!(error instanceof DOMException && error.name === "AbortError")) setState("error");
    });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void Promise.all([getExecutionStatus(controller.signal), getPaperPositions(controller.signal), getBacktestResearch(controller.signal)])
      .then(([status, paperPositions, comparison]) => { setExecution(status); setPositions(paperPositions); setResearch(comparison); })
      .catch(() => undefined);
    return () => controller.abort();
  }, []);

  const equity = useMemo(() => trades.reduce((total, trade) => total + trade.net_pnl, 0), [trades]);
  const metrics = run?.metrics;
  return <div className={styles.page}>
    <PageHeader title="Strategy" meta="Historical replay · ECHO Residual Propagation v1" />
    <div className={styles.banner}><span className={styles.mode}>BACKTEST</span><span>Frozen configuration · no live performance claim</span><span className={styles.hash}>{run ? run.config_hash.slice(0, 12) : "echo-rp-v1"}</span></div>
    {state === "loading" && <section className={styles.state}>Loading registered replay runs…</section>}
    {state === "error" && <section className={styles.state}><strong>Replay unavailable</strong><p>Start the API and run <code>make backtest-final</code> to populate this workspace.</p></section>}
    {state === "empty" && <section className={styles.state}><strong>No backtest run yet</strong><p>The Strategy screen stays explicit until a registered historical replay exists.</p></section>}
    {state === "ready" && run && <>
      <section className={styles.heroGrid} aria-label="Backtest summary">
        <article className={styles.hero}><span className={styles.kicker}>STRATEGY</span><h2>ECHO Residual Propagation <em>v1</em></h2><p>Event severity → graph exposure → forecast → underabsorption → confirmation → controlled entry.</p><div className={styles.tags}><span>TEST</span><span>HISTORICAL REPLAY</span><span>{metrics?.status}</span></div></article>
        <article className={styles.config}><span className={styles.kicker}>CURRENT CONFIGURATION</span><dl><div><dt>Horizon</dt><dd>1D · 2D · 5D</dd></div><div><dt>Probability</dt><dd>≥ 60%</dd></div><div><dt>Graph exposure</dt><dd>≥ 0.20</dd></div><div><dt>Risk / trade</dt><dd>0.75%</dd></div><div><dt>Stop</dt><dd>1.5 × risk</dd></div><div><dt>Hedge</dt><dd>NONE</dd></div></dl></article>
      </section>
      <section className={styles.metricGrid} aria-label="Backtest metrics">
        <Metric label="Return" value={percent(metrics?.total_return ?? null)} /><Metric label="Sharpe" value={ratio(metrics?.sharpe ?? null)} /><Metric label="Sortino" value={ratio(metrics?.sortino ?? null)} /><Metric label="Max DD" value={percent(metrics?.max_drawdown ?? null)} /><Metric label="Win rate" value={percent(metrics?.hit_rate ?? null)} /><Metric label="Trades" value={String(metrics?.trades ?? 0)} />
      </section>
      <section className={styles.panel}><div className={styles.panelHeader}><div><span className={styles.kicker}>EQUITY CURVE</span><h2>Replay outcome</h2></div><span className={styles.subtle}>Dataset {run.dataset_hash.slice(0, 12)}…</span></div><div className={styles.curve}><span className={styles.axis}>$100k</span><div className={styles.curveLine} style={{ "--curve-rise": `${Math.max(-30, Math.min(30, equity / 100))}px` } as CSSProperties} /><span className={styles.axisBottom}>0</span></div></section>
      <section className={styles.panel}><div className={styles.panelHeader}><div><span className={styles.kicker}>TRADE LEDGER</span><h2>Why this trade?</h2></div><span className={styles.subtle}>{trades.length} cases · losing trades remain visible</span></div><div className={styles.tableWrap}><table><thead><tr><th>Symbol</th><th>Side</th><th>Event</th><th>Forecast</th><th>Entry → Exit</th><th>Net P&amp;L</th><th>Decision</th></tr></thead><tbody>{trades.slice(-12).map((trade) => <tr key={trade.case_key}><td><strong>{trade.symbol}</strong><small>{trade.sector}</small></td><td><span className={trade.side === "LONG" ? styles.long : styles.short}>{trade.side}</span></td><td>{trade.event_class}</td><td>{percent(trade.forecast_q50)}</td><td>{trade.entry_price?.toFixed(2) ?? "—"} → {trade.exit_price?.toFixed(2) ?? "—"}</td><td className={trade.net_pnl >= 0 ? styles.positive : styles.negative}>{trade.net_pnl >= 0 ? "+" : ""}{trade.net_pnl.toFixed(2)}</td><td><span className={styles.reason}>{trade.decision_reasons[0] ?? trade.status}</span></td></tr>)}</tbody></table></div></section>
      <section className={styles.lowerGrid}><article className={styles.panel}><div className={styles.panelHeader}><div><span className={styles.kicker}>ABLATIONS</span><h2>Evidence ladder</h2></div></div><p className={styles.note}>S0–S6 baselines and minus-graph/absorption/confirmation variants are registered in the research command. They are not promoted until a real event archive exists.</p></article><article className={styles.panel}><div className={styles.panelHeader}><div><span className={styles.kicker}>ROBUSTNESS</span><h2>Costs · delays · holdout</h2></div></div><p className={styles.note}>Cost multipliers 1× / 2× / 3× and delayed-entry variants are kept separate from the frozen configuration. Final test stays untouched.</p></article></section>
      <section className={styles.executionGrid} aria-label="Paper execution">
        <article className={styles.panel}><div className={styles.panelHeader}><div><span className={styles.kicker}>PAPER EXECUTION</span><h2>Broker boundary</h2></div><span className={execution?.kill_switch ? styles.danger : styles.liveBadge}>{execution?.kill_switch ? "TRADING PAUSED" : execution?.mode ?? "UNKNOWN"}</span></div><div className={styles.executionRows}><div><span>Provider</span><strong>{execution?.provider ?? "—"}</strong></div><div><span>Connection</span><strong>{execution?.healthy ? "HEALTHY" : execution?.configured ? "DEGRADED" : "UNCONFIGURED"}</strong></div><div><span>Reconciliation</span><strong>{execution?.reconciliation_state ?? "—"}</strong></div><div><span>Positions</span><strong>{positions.length}</strong></div></div><p className={styles.note}>Only validated <code>PAPER_TRADE</code> decisions can create an OrderIntent. Simulation and broker fills remain separate.</p></article>
        <article className={styles.panel}><div className={styles.panelHeader}><div><span className={styles.kicker}>CONVICTION HANDOFF</span><h2>Frozen strategy prompt</h2></div><button className={styles.copyButton} type="button" onClick={() => { void navigator.clipboard?.writeText("ECHO Residual Propagation echo-rp-v1 · PAPER only · next-bar entry · 0.75% risk · 1D/2D/5D"); setCopied(true); }}>{copied ? "Copied" : "Copy prompt"}</button></div><p className={styles.note}>The generated Conviction prompt is an exact handoff, not an execution authority.</p></article>
      </section>
      {research && <section className={styles.panel}><div className={styles.panelHeader}><div><span className={styles.kicker}>BASELINES + ABLATIONS</span><h2>Computed comparison</h2></div><span className={styles.subtle}>{research.trials_count} registered trials · fixture validation</span></div><div className={styles.comparison}>{Object.entries(research.families).map(([name, value]) => <div className={styles.comparisonRow} key={name}><strong>{name.replaceAll("_", " ")}</strong><span>{percent(value.total_return)}</span><span>{ratio(value.sharpe)}</span><span>{percent(value.max_drawdown)}</span><span>{value.trades} trades</span><small>{value.status}</small></div>)}</div></section>}
      {trades.find((trade) => trade.side !== "NO_TRADE") && <section className={styles.panel}><div className={styles.panelHeader}><div><span className={styles.kicker}>REPLAY TIMELINE</span><h2>Evidence chain</h2></div><span className={styles.subtle}>knowledge available at simulated cutoff only</span></div><div className={styles.timeline}>{["World event known", "Graph exposure projected", "Forecast vintage frozen", "Decision gate", "Next-bar execution", "Horizon / stop exit", "Realized result"].map((step, index) => <div className={styles.timelineStep} key={step}><span>{String(index + 1).padStart(2, "0")}</span><strong>{step}</strong></div>)}</div></section>}
    </>}
  </div>;
}

function Metric({ label, value }: { label: string; value: string }) { return <article className={styles.metric}><span>{label}</span><strong>{value}</strong></article>; }
