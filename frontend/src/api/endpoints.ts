import { api } from "./client";
import { streamRequest } from "./stream";
import type {
  AdminOverview,
  AdminTrip,
  AdminUser,
  ApprovalInput,
  AuditLog,
  ProgressEvent,
  RequestLog,
  SessionResponse,
  SqlLog,
  SystemInfo,
  TripPayload,
  TripSummary,
} from "./types";

export const getSession = () => api<SessionResponse>("/api/session");

export const login = (email: string, password: string) =>
  api<{ success: boolean }>("/api/auth/login", { method: "POST", json: { email, password } });

export const register = (email: string, password: string, name: string) =>
  api<{ success: boolean; message: string }>("/api/auth/register", { method: "POST", json: { email, password, name } });

export const forgotPassword = (email: string) =>
  api<{ success: boolean; message: string }>("/api/auth/forgot", { method: "POST", json: { email } });

export const resetPassword = (token: string, password: string) =>
  api<{ success: boolean }>("/api/auth/reset", { method: "POST", json: { token, password } });

export const logout = () => api<{ success: boolean }>("/api/session", { method: "DELETE" });

export const deleteAccount = () =>
  api<{ success: boolean; trips_deleted: number }>("/api/account/delete", { method: "POST", json: { confirm: true } });

export const listTrips = () => api<{ trips: TripSummary[] }>("/api/travel/threads").then((r) => r.trips);

export const getTrip = (threadId: string) => api<TripPayload>(`/api/travel/${encodeURIComponent(threadId)}`);

export const deleteTrip = (threadId: string) =>
  api<{ success: boolean }>(`/api/travel/${encodeURIComponent(threadId)}`, { method: "DELETE" });

export const startTrip = (message: string, onProgress: (e: ProgressEvent) => void, signal?: AbortSignal) =>
  streamRequest("/api/travel/stream", { message }, onProgress, signal);

export const reviewTrip = (input: ApprovalInput, onProgress: (e: ProgressEvent) => void, signal?: AbortSignal) =>
  streamRequest("/api/travel/approve/stream", input, onProgress, signal);

/* ---------- Admin console ---------- */
function query(params: Record<string, string | number | boolean | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "" && value !== false) search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

export const adminOverview = () => api<AdminOverview & { success: boolean }>("/api/admin/overview");

export const adminUsers = (params: { q?: string; limit?: number; offset?: number }) =>
  api<{ total: number; users: AdminUser[] }>(`/api/admin/users${query(params)}`);

export const adminUpdateUser = (id: string, change: { role?: "user" | "admin"; is_active?: boolean; verify_email?: boolean }) =>
  api<{ user: AdminUser }>(`/api/admin/users/${id}`, { method: "PATCH", json: change });

export const adminRevokeSessions = (id: string) =>
  api<{ success: boolean }>(`/api/admin/users/${id}/revoke-sessions`, { method: "POST" });

export const adminDeleteUser = (id: string) =>
  api<{ trips_deleted: number }>(`/api/admin/users/${id}`, { method: "DELETE" });

export const adminTrips = (params: { status?: string; owner?: string; limit?: number; offset?: number }) =>
  api<{ total: number; trips: AdminTrip[] }>(`/api/admin/trips${query(params)}`);

export const adminDeleteTrip = (id: string) => api<{ success: boolean }>(`/api/admin/trips/${id}`, { method: "DELETE" });

export const adminRequestLogs = (params: { status?: string; method?: string; path?: string; min_ms?: number; limit?: number; offset?: number }) =>
  api<{ logs: RequestLog[] }>(`/api/admin/logs/requests${query(params)}`);

export const adminSqlLogs = (params: { q?: string; slow?: boolean; errors?: boolean; limit?: number }) =>
  api<{ enabled: boolean; slow_threshold_ms: number; summary: AdminOverview["sql"]; logs: SqlLog[] }>(
    `/api/admin/logs/sql${query(params)}`,
  );

export const adminAuditLogs = (params: { limit?: number; offset?: number } = {}) =>
  api<{ logs: AuditLog[] }>(`/api/admin/logs/audit${query(params)}`);

export const adminSystem = () => api<SystemInfo>("/api/admin/system");

export const adminPurge = () => api<{ trips_removed: number }>("/api/admin/system/purge", { method: "POST" });
