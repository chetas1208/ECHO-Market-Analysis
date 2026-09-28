export type OperationalState = "HEALTHY" | "DEGRADED" | "UNAVAILABLE";

export interface OperationalDependency {
  state: OperationalState;
  status: string;
  detail: string;
}

export interface OperationalStatus {
  status: OperationalState;
  checked_at: string;
  dependencies: Record<string, OperationalDependency>;
  liveness: "ok";
}
