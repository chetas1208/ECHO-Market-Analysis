export type ForecastHorizonKey = "1D" | "2D" | "5D" | "10D" | "20D";

export interface ForecastHorizon {
  horizon: ForecastHorizonKey;
  trading_days: number;
  target_timestamp: string | null;
  q10: number | null;
  q50: number | null;
  q90: number | null;
  probability_positive: number | null;
  risk: number | null;
  confidence: number | null;
  score: number | null;
}

export interface ForecastPreview {
  event_id: string;
  symbol: string;
  issued_at: string;
  data_cutoff_at: string;
  graph_snapshot_id: string | null;
  model_version: string;
  feature_version: string;
  feature_hash: string;
  model_artifact_hash: string | null;
  horizons: Partial<Record<ForecastHorizonKey, ForecastHorizon>>;
  recommended_horizon: ForecastHorizonKey | null;
  information_half_life: number | null;
  model_status: "READY" | "FORECAST_UNAVAILABLE";
  unavailable_reason: string | null;
  diagnostics: Record<string, unknown>;
}

export interface ForecastingStatus {
  artifact_available: boolean;
  model_status: string;
  model_version: string | null;
  feature_version: string | null;
  training_cutoff: string | null;
  artifact_hash: string | null;
  backend: string | null;
  chronos_status: string;
  chronos_model: string;
  artifact_path: string;
}
