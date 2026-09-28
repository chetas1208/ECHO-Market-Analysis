/** Shared API contract types (backend: /api/v1). */

export type ApiErrorCode =
  | "validation_error"
  | "not_found"
  | "conflict"
  | "database_error"
  | "internal_error"
  | "method_not_allowed"
  | "http_error";

export interface ApiErrorBody {
  code: ApiErrorCode;
  message: string;
  details?: unknown;
  request_id: string;
}

export interface ApiErrorEnvelope {
  error: ApiErrorBody;
}

export interface Paginated<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface HealthResponse {
  status: "ok";
}

export interface ReadyResponse {
  status: "ready" | "not_ready";
  checks: Record<string, string>;
}
