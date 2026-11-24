import { api } from "./client";
import { streamRequest } from "./stream";
import type { ApprovalInput, ProgressEvent, SessionResponse, TripPayload, TripSummary } from "./types";

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
