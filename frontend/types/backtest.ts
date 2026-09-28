export interface BacktestMetrics {
  status: string;
  total_return: number;
  annualized_return: number | null;
  sharpe: number | null;
  sortino: number | null;
  max_drawdown: number;
  hit_rate: number | null;
  profit_factor: number | null;
  trades: number;
  trades_per_week: number | null;
  long_trades: number;
  short_trades: number;
}

export interface BacktestRun {
  run_id: string;
  strategy_version: string;
  config_hash: string;
  dataset_hash: string;
  split: "TRAIN" | "VALIDATION" | "TEST";
  mode: "HISTORICAL_REPLAY";
  metrics: BacktestMetrics;
  artifact_path: string | null;
}

export interface BacktestTrade {
  case_key: string;
  event_id: string;
  event_class: string;
  symbol: string;
  sector: string;
  side: "LONG" | "SHORT" | "NO_TRADE";
  signal_timestamp: string;
  entry_timestamp: string | null;
  exit_timestamp: string | null;
  horizon: string;
  forecast_q50: number | null;
  probability_positive: number | null;
  graph_exposure: number | null;
  cause_score: number | null;
  absorption_ratio: number | null;
  decision_reasons: string[];
  entry_price: number | null;
  exit_price: number | null;
  costs: number;
  gross_pnl: number;
  net_pnl: number;
  status: string;
  exit_reason: string | null;
  notional: number;
}

export interface BacktestList {
  items: BacktestRun[];
  total: number;
}
