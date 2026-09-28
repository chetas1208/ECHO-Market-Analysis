"use client";

import { useCallback, useMemo, useState } from "react";
import { getEventGraph, listEvents } from "@/lib/api";
import { useApiResource } from "@/lib/useApiResource";
import type { EchoEvent } from "@/types/event";
import type { GraphEdge, GraphNode, GraphProjection } from "@/types/graph";
import { PageHeader } from "./PageHeader";
import { ShockInvestigator } from "./ShockInvestigator";
import styles from "./ShockGraph.module.css";

const nodeOrder: Record<string, number> = {
  channel: 0,
  commodity: 1,
  geography: 1,
  technology: 1,
  sector: 1,
  infrastructure: 1,
  company: 2,
};

function score(value: number) {
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}`;
}

function nodeLabel(node: GraphNode) {
  return node.symbol || node.canonical_name;
}

function nodePosition(node: GraphNode, nodes: GraphNode[]) {
  const column = nodeOrder[node.node_type] ?? 1;
  const same = nodes.filter((item) => (nodeOrder[item.node_type] ?? 1) === column);
  return { x: column === 0 ? 110 : column === 2 ? 650 : 380, y: 70 + same.indexOf(node) * 55 };
}

function GraphCanvas({ projection, selectedNode, selectedEdge, onNode, onEdge }: {
  projection: GraphProjection;
  selectedNode: string | null;
  selectedEdge: string | null;
  onNode: (node: GraphNode) => void;
  onEdge: (edge: GraphEdge) => void;
}) {
  const height = Math.max(560, 100 + Math.max(...projection.nodes.map((node) => nodePosition(node, projection.nodes).y), 100));
  const positions = useMemo(() => new Map(projection.nodes.map((node) => [node.id, nodePosition(node, projection.nodes)])), [projection.nodes]);
  return (
    <div className={styles.canvas} data-testid="shockgraph-canvas">
      <div className={styles.canvasHeader}>
        <span className="label">economic path view</span>
        <div className={styles.legend}><span className={styles.positive}>positive</span><span className={styles.negative}>negative</span></div>
      </div>
      <svg viewBox={`0 0 760 ${height}`} role="img" aria-label="ShockGraph event propagation graph">
        {projection.edges.map((edge) => {
          const source = positions.get(edge.source_node_id);
          const target = positions.get(edge.target_node_id);
          if (!source || !target) return null;
          return <line key={edge.id} className={styles.edge} data-selected={selectedEdge === edge.id} x1={source.x} y1={source.y} x2={target.x} y2={target.y} stroke={edge.sign > 0 ? "var(--pos)" : "var(--neg)"} role="button" tabIndex={0} aria-label={`${edge.relationship_type} ${edge.sign > 0 ? "positive" : "negative"}`} onClick={() => onEdge(edge)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") onEdge(edge); }} />;
        })}
        {projection.nodes.map((node) => {
          const position = positions.get(node.id);
          if (!position) return null;
          return <g key={node.id} className={`${styles.node} ${node.node_type}`} data-selected={selectedNode === node.id} transform={`translate(${position.x} ${position.y})`} role="button" tabIndex={0} aria-label={`${node.node_type} ${nodeLabel(node)}`} onClick={() => onNode(node)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") onNode(node); }}>
            {node.node_type === "commodity" ? <polygon points="0,-15 15,0 0,15 -15,0" /> : node.node_type === "geography" || node.node_type === "channel" ? <rect x="-16" y="-13" width="32" height="26" rx="5" /> : <circle r={node.node_type === "company" ? 17 : 14} />}
            <text y="31">{nodeLabel(node).slice(0, 18)}</text>
          </g>;
        })}
      </svg>
    </div>
  );
}

function Inspector({ node, edge }: { node: GraphNode | null; edge: GraphEdge | null }) {
  if (!node && !edge) return <div className={styles.panel}><span className={styles.panelTitle}>Inspector</span><h2>Select a graph element</h2><p>Choose a node or relationship to inspect its economic meaning and provenance.</p></div>;
  if (edge) return <div className={styles.panel} data-testid="graph-edge-inspector"><span className={styles.panelTitle}>Relationship</span><h2>{edge.relationship_type}</h2><dl className={styles.facts}><dt>Direction</dt><dd>{edge.sign > 0 ? "Positive" : "Negative"}</dd><dt>Weight</dt><dd className="mono">{edge.weight.toFixed(2)}</dd><dt>Confidence</dt><dd className="mono">{edge.confidence.toFixed(2)}</dd><dt>Valid from</dt><dd className="mono">{edge.valid_from.slice(0, 10)}</dd></dl><div className={styles.provenance}><span className={styles.panelTitle}>Provenance</span><pre>{JSON.stringify(edge.provenance, null, 2)}</pre></div></div>;
  return <div className={styles.panel} data-testid="graph-node-inspector"><span className={styles.panelTitle}>{node?.node_type}</span><h2>{node?.symbol || node?.canonical_name}</h2><p>{node?.canonical_name}</p><div className={styles.provenance}><span className={styles.panelTitle}>Metadata</span><pre>{JSON.stringify(node?.metadata || {}, null, 2)}</pre></div></div>;
}

export function ShockGraphWorkspace() {
  const eventsResource = useApiResource(useCallback((signal: AbortSignal) => listEvents({ limit: 100, signal }), []));
  const [eventId, setEventId] = useState("");
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<GraphEdge | null>(null);
  const [maxDepth, setMaxDepth] = useState(3);
  const [direction, setDirection] = useState<"all" | "positive" | "negative">("all");
  const selectedEventId = eventId || (eventsResource.state.status === "success" ? eventsResource.state.data.items[0]?.id || "" : "");
  const fetchGraph = useCallback((signal: AbortSignal) => getEventGraph(selectedEventId, { maxDepth, signal }), [selectedEventId, maxDepth]);
  const graphResource = useApiResource(fetchGraph, Boolean(selectedEventId));
  const event = eventsResource.state.status === "success" ? eventsResource.state.data.items.find((item) => item.id === selectedEventId) : undefined;
  const projection = graphResource.state.status === "success" ? graphResource.state.data : null;
  const visibleCompanies = projection?.companies.filter((item) => direction === "all" || item.direction.toLowerCase() === direction) || [];
  const selectedEdgeFromProjection = projection?.edges.find((item) => item.id === selectedEdge?.id) || null;
  const selectedNodeFromProjection = projection?.nodes.find((item) => item.id === selectedNode?.id) || null;

  return <div className={styles.page}>
    <PageHeader title="ShockGraph" meta="Causal workspace · event to company exposure" />
    <div className={styles.controls}>
      <label className="sr-only" htmlFor="graph-event">Event</label>
      <select id="graph-event" className={styles.select} value={selectedEventId} onChange={(e) => { setEventId(e.target.value); setSelectedNode(null); setSelectedEdge(null); }} aria-label="Select event">
        <option value="">Select event</option>
        {eventsResource.state.status === "success" ? eventsResource.state.data.items.map((item: EchoEvent) => <option key={item.id} value={item.id}>{item.title}</option>) : null}
      </select>
      <span className="label">max depth</span>
      {[1, 2, 3].map((depth) => <button key={depth} className={styles.control} data-active={maxDepth === depth} type="button" onClick={() => setMaxDepth(depth)}>{depth}</button>)}
      {(["all", "positive", "negative"] as const).map((value) => <button key={value} className={styles.control} data-active={direction === value} type="button" onClick={() => setDirection(value)}>{value}</button>)}
    </div>
    {eventsResource.state.status === "error" ? <div className={styles.state}><h2>Events unavailable</h2><p>{eventsResource.state.error.message}</p></div> : !selectedEventId ? <div className={styles.state}><h2>Select an event</h2><p>ShockGraph starts from canonical economic channels, not headline sentiment.</p></div> : graphResource.state.status === "loading" ? <div className={styles.state}><h2>Loading graph</h2><p>Resolving the active immutable snapshot.</p></div> : graphResource.state.status === "error" ? <div className={styles.state}><h2>Graph snapshot unavailable</h2><p>{graphResource.state.error.message}. Create a validated snapshot before exploring exposures.</p></div> : projection && event ? <>
      <section className="card" aria-labelledby="graph-event-title"><div className="label">selected event · {event.source_type.toUpperCase()} · {event.event_type}</div><h2 id="graph-event-title">{event.title}</h2><p className="muted">Severity {event.severity.toFixed(2)} · Confidence {event.confidence.toFixed(2)} · Channels are directional pressure, not expected price moves.</p></section>
      <ShockInvestigator event={event} />
      <div className={styles.layout}>
        <GraphCanvas projection={{ ...projection, companies: visibleCompanies }} selectedNode={selectedNode?.id || null} selectedEdge={selectedEdge?.id || null} onNode={(node) => { setSelectedNode(node); setSelectedEdge(null); }} onEdge={(edge) => { setSelectedEdge(edge); setSelectedNode(null); }} />
        <Inspector node={selectedNodeFromProjection} edge={selectedEdgeFromProjection} />
        <section className={styles.ranking} aria-labelledby="exposure-ranking-title"><div className={styles.rankingTitle} id="exposure-ranking-title">Ranked company exposure · snapshot {projection.graph_snapshot_id}</div><div className={styles.rankingList}>{visibleCompanies.length ? visibleCompanies.map((item) => <button className={styles.company} key={item.symbol} type="button" onClick={() => { const node = projection.nodes.find((candidate) => candidate.id === item.node_id); if (node) { setSelectedNode(node); setSelectedEdge(null); } }}><strong>{item.symbol}</strong><small>{item.top_reason || "graph path"}</small><span className={item.direction === "POSITIVE" ? styles.positive : styles.negative}>{score(item.exposure)}</span></button>) : <p className="muted">No exposure above the configured threshold.</p>}</div></section>
      </div>
    </> : null}
  </div>;
}
