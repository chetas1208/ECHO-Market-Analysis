export interface ExecutionStatus {
  mode: "DISABLED" | "REPLAY" | "PAPER";
  provider: string;
  configured: boolean;
  healthy: boolean;
  account_status: string | null;
  kill_switch: boolean;
  data_fresh: boolean;
  reconciliation_state: string;
  message: string | null;
}

export interface PaperPosition {
  symbol: string;
  side: string;
  quantity: number;
  average_entry_price: number | null;
  current_price: number | null;
  unrealized_pnl: number | null;
}
