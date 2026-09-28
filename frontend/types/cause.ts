export type CauseMode = "REALTIME" | "RETROSPECTIVE";
export type CauseStatus = "IDENTIFIED" | "AMBIGUOUS" | "UNKNOWN";
export type ResponseState =
  | "NOT_OBSERVED"
  | "OPPOSITE"
  | "UNCONFIRMED"
  | "PARTIAL"
  | "CONFIRMED"
  | "OVERREACTING";

export interface CauseCandidate {
  event_id: string;
  title: string;
  score: number;
  temporal_score: number;
  entity_score: number;
  economic_score: number;
  graph_score: number;
  market_score: number;
  source_score: number;
  directional_consistency: number;
  evidence: Array<Record<string, unknown>>;
  graph_paths: Array<Record<string, unknown>>;
}

export interface CauseInvestigation {
  investigation_id: string;
  shock_event_id: string;
  graph_snapshot_id: string;
  created_at: string;
  data_cutoff_at: string;
  mode: CauseMode;
  status: CauseStatus;
  engine_version: string;
  config_version: string;
  config_hash: string;
  candidates: CauseCandidate[];
  metadata: Record<string, unknown>;
}

export interface MarketImpactCompany {
  symbol: string;
  exposure: number;
  confidence: number;
  actual_residual_z: number | null;
  response_state: ResponseState;
  paths: Array<Record<string, unknown>>;
}

export interface MarketImpact {
  event_id: string;
  graph_snapshot_id: string;
  graph_version: string;
  data_cutoff_at: string;
  market_confirmation_unavailable: boolean;
  companies: MarketImpactCompany[];
  unmapped_channels: string[];
}

export interface ClusterShock {
  cluster_id: string;
  cluster_key: string;
  as_of: string;
  direction: "POSITIVE" | "NEGATIVE";
  members: string[];
  member_count: number;
  abnormal_count: number;
  strength: number;
  synchronization: number;
  volume_confirmation: number;
  graph_connectivity: number;
  source_event_id: string | null;
  metadata: Record<string, unknown>;
}

export interface ClusterShockList {
  items: ClusterShock[];
  total: number;
}
