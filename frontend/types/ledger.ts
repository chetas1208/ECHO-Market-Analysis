import type { ForecastHorizonKey, ForecastPreview } from "@/types/forecast";

export interface ForecastPoint {
  horizon: ForecastHorizonKey;
  horizon_trading_days: number;
  target_timestamp: string;
  q10: number;
  q50: number;
  q90: number;
  probability_positive: number;
  expected_abnormal_return: number | null;
  forecast_risk: number | null;
}

export interface ForecastVintage {
  id: string;
  event_id: string | null;
  symbol: string;
  issued_at: string;
  data_cutoff_at: string;
  created_at: string;
  graph_snapshot_id: string | null;
  event_snapshot_id: string | null;
  event_snapshot: Record<string, unknown> | null;
  model_version: string;
  feature_version: string;
  model_artifact_hash: string | null;
  feature_hash: string | null;
  feature_snapshot: Record<string, unknown>;
  config_hash: string | null;
  forecasting_engine_version: string;
  recommended_horizon: ForecastHorizonKey | null;
  information_half_life: number | null;
  ood_status: string | null;
  abstention_state: string | null;
  content_hash: string | null;
  request_hash: string | null;
  horizons: ForecastPoint[];
}

export interface ForecastVintageList {
  items: ForecastVintage[];
  total: number;
  limit: number;
  offset: number;
}

export interface ForecastEvaluation {
  forecast_run_id: string;
  horizon: ForecastHorizonKey;
  status: "PENDING" | "PARTIAL" | "COMPLETE" | "UNAVAILABLE";
  evaluated_at: string;
  predicted_q10: number | null;
  predicted_q50: number | null;
  predicted_q90: number | null;
  probability_positive: number | null;
  actual_abnormal_return: number | null;
  absolute_error: number | null;
  squared_error: number | null;
  directional_correct: boolean | null;
  interval_covered: boolean | null;
  pinball_q10: number | null;
  pinball_q50: number | null;
  pinball_q90: number | null;
  brier_contribution: number | null;
}

export interface SimulatedTrade {
  id: string;
  forecast_run_id: string;
  created_at: string;
  symbol: string;
  side: "LONG" | "SHORT" | "NO_TRADE";
  decision_timestamp: string;
  entry_timestamp: string | null;
  entry_price: number | null;
  planned_exit_horizon: ForecastHorizonKey;
  planned_exit_timestamp: string;
  position_size: number;
  notional: number;
  hedge_symbol: string | null;
  hedge_ratio: number;
  stop_type: string | null;
  stop_value: number | null;
  strategy_version: string;
  config_hash: string;
  status: string;
  gross_pnl: number;
  costs: number;
  hedge_pnl: number;
  net_pnl: number;
  return_on_allocated_capital: number | null;
  plan_hash: string;
  reason: string | null;
}

export interface PortfolioState {
  initial_equity: number;
  cash: number;
  gross_exposure: number;
  net_exposure: number;
  equity: number;
  realized_pnl: number;
  unrealized_pnl: number;
  trade_count: number;
}

export type ForecastPreviewOrVintage = ForecastPreview | ForecastVintage;
