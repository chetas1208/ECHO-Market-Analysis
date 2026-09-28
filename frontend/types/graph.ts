export type GraphNodeType =
  | "company"
  | "commodity"
  | "geography"
  | "technology"
  | "sector"
  | "infrastructure"
  | "channel";

export interface GraphNode {
  id: string;
  node_type: GraphNodeType;
  canonical_name: string;
  symbol: string | null;
  external_ids: Record<string, unknown>;
  metadata: Record<string, unknown>;
}

export interface GraphEdge {
  id: string;
  source_node_id: string;
  target_node_id: string;
  relationship_type: string;
  sign: -1 | 1;
  weight: number;
  confidence: number;
  provenance: Record<string, unknown>;
  valid_from: string;
  valid_to: string | null;
}

export interface GraphPath {
  nodes: string[];
  edge_ids: string[];
  relationships: string[];
  contribution: number;
  confidence: number;
  depth: number;
}

export interface CompanyExposure {
  symbol: string;
  node_id: string;
  company_name: string;
  exposure: number;
  confidence: number;
  rank: number;
  paths: GraphPath[];
  direction: "POSITIVE" | "NEGATIVE";
  top_reason: string | null;
}

export interface GraphProjection {
  event_id: string;
  graph_snapshot_id: string;
  graph_version: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
  companies: CompanyExposure[];
  unmapped_channels: string[];
  diagnostics: {
    status: string;
    channel_count: number;
    unmapped_channel_count: number;
    duration_ms?: number;
  };
}
