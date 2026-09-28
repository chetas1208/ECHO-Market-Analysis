import type { Paginated } from "./api";

export type SourceType = "world" | "market" | "financial";

/** Canonical ECHO event (Plan.md section 7). Named EchoEvent to avoid the DOM `Event`. */
export interface EchoEvent {
  /** "evt_..." */
  id: string;
  /** ISO 8601 */
  timestamp: string;
  source_type: SourceType;
  event_type: string;
  title: string;
  summary: string | null;
  entities: string[];
  companies: string[];
  locations: string[];
  /** channel name -> signed exposure in [-1, 1] */
  economic_channels: Record<string, number>;
  /** All scores are in [0, 1]. */
  severity: number;
  novelty: number;
  corroboration: number;
  confidence: number;
  source_refs: Array<Record<string, unknown>>;
  metadata: Record<string, unknown>;
  is_mock: boolean;
  created_at: string;
  ingested_at: string;
  /** Day 3 additions (optional: absent on Day 1/2 payloads). */
  revision?: number;
  updated_at?: string | null;
  source_count?: number;
  independent_source_count?: number;
}

export type EventListResponse = Paginated<EchoEvent>;
