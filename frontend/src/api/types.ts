export interface User {
  email: string;
  name: string;
  has_password: boolean;
  has_google: boolean;
  role: "user" | "admin";
}

export interface Providers {
  google: boolean;
  password: boolean;
}

export interface SessionResponse {
  success: boolean;
  authenticated: boolean;
  user: User | null;
  providers: Providers;
}

export type TripStatus = "awaiting_approval" | "completed" | "blocked" | "failed" | "running";

export interface TripSummary {
  thread_id: string;
  title: string;
  status: TripStatus;
  created_at: string;
  updated_at: string;
}

export interface TripPayload {
  success: boolean;
  thread_id: string;
  status: TripStatus;
  user_query: string;
  answer: string;
  itinerary: string;
  requires_approval: boolean;
  approval_request: string;
  flight_results: string;
  hotel_results: string;
  weather_results: string;
  budget_results: string;
  selected_agents: string[];
  supervisor_reasoning: string;
  guardrail_allowed: boolean;
  guardrail_reason: string;
  revision_count: number;
  max_revisions: number;
  llm_calls: number;
}

export interface ProgressEvent {
  type: "progress";
  node: string;
  label: string;
  state: "start" | "done" | "failed";
}

export interface ApprovalInput {
  thread_id: string;
  approved: boolean;
  feedback: string;
}

/* ---------- Admin console ---------- */
export interface AdminUser {
  id: string;
  email: string;
  name: string;
  role: "user" | "admin";
  email_verified: boolean;
  has_password: boolean;
  has_google: boolean;
  is_active: boolean;
  created_at: string;
  last_login: string | null;
  trips: number;
}

export interface AdminTrip {
  thread_id: string;
  owner_id: string;
  owner_email: string;
  title: string;
  status: TripStatus;
  created_at: string;
  updated_at: string;
}

export interface RequestStats {
  hours: number;
  total: number;
  client_errors: number;
  server_errors: number;
  avg_ms: number;
  p95_ms: number;
  series: { hour: string; requests: number; errors: number }[];
}

export interface AdminOverview {
  users: { total: number; verified: number; admins: number; disabled: number; new_7d: number; google: number };
  trips: { by_status: Record<string, number>; last_24h: number; total: number };
  requests: RequestStats;
  sql: { count: number; slow: number; errors: number; avg_ms: number; max_ms: number };
  ready: { ready: boolean; database: string };
}

export interface RequestLog {
  id: number;
  ts: string;
  request_id: string;
  method: string;
  path: string;
  status: number;
  duration_ms: number;
  user_id: string | null;
  ip: string;
}

export interface SqlLog {
  id: number;
  ts: string;
  sql: string;
  duration_ms: number;
  rows: number | null;
  error: string;
  request_id: string;
  slow: boolean;
}

export interface AuditLog {
  id: number;
  ts: string;
  actor_id: string;
  actor_email: string;
  action: string;
  target: string;
  detail: string;
  ip: string;
}

export interface SystemInfo {
  version: string;
  ready: { ready: boolean; database: string };
  settings: Record<string, string | number | boolean>;
  integrations: Record<string, boolean | null>;
  password_policy: { min_length: number; roles: string[] };
}
