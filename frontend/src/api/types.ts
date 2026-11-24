export interface User {
  email: string;
  name: string;
  has_password: boolean;
  has_google: boolean;
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
