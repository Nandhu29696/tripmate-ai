import type { TripStatus } from "../api/types";

export const STATUS_LABEL: Record<TripStatus, string> = {
  awaiting_approval: "Needs your review",
  completed: "Final plan ready",
  blocked: "Outside travel scope",
  failed: "Did not finish",
  running: "In progress",
};

export const AGENT_LABEL: Record<string, string> = {
  flight_agent: "Flights",
  hotel_agent: "Hotels",
  weather_agent: "Weather",
  budget_agent: "Budget",
  itinerary_agent: "Itinerary",
};

export function timeAgo(iso: string, now: number = Date.now()): string {
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return "";
  const seconds = Math.max(0, Math.round((now - then) / 1000));
  if (seconds < 60) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days} d ago`;
  return new Date(then).toLocaleDateString();
}

export function firstName(name: string): string {
  return name.trim().split(/\s+/)[0] || "there";
}

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  const letters = parts.length > 1 ? [parts[0]?.[0], parts[parts.length - 1]?.[0]] : [parts[0]?.[0]];
  return (letters.filter(Boolean).join("") || "?").toUpperCase();
}

/**
 * 0 (empty) to 4 (strong). Anything under the server's 10-character minimum is level 1
 * ("Too short"), so the meter always gives feedback once the user starts typing.
 */
export function passwordStrength(password: string): number {
  if (!password) return 0;
  if (password.length < 10) return 1;

  let level = 2; // meets the minimum
  if (password.length >= 14) level++;
  if (password.length >= 20) level++; // long passphrases are strong even without capitals or digits
  if (/[A-Z]/.test(password) || /\d/.test(password) || /[^A-Za-z0-9]/.test(password)) level++;
  return Math.min(4, level);
}

/** Where to go after signing in: the page the visitor originally asked for, if it is an in-app path. */
export function returnPath(state: unknown): string {
  const from = (state as { from?: unknown } | null)?.from;
  return typeof from === "string" && from.startsWith("/") && !from.startsWith("//") && !from.startsWith("/login") ? from : "/";
}

/** "24 Nov, 14:05:09" in the viewer's locale and time zone. */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "-";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "-";
  return `${date.toLocaleDateString(undefined, { day: "numeric", month: "short" })}, ${date.toLocaleTimeString(undefined, { hour12: false })}`;
}

export function formatMs(ms: number): string {
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.round(ms)} ms`;
}
