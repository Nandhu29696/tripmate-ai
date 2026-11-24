import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import { App } from "../App";
import * as endpoints from "../api/endpoints";
import type { Providers, SessionResponse, TripPayload, User } from "../api/types";

export const USER: User = { email: "ada@example.com", name: "Ada Lovelace", has_password: true, has_google: false };

export function session(authenticated: boolean, providers: Partial<Providers> = {}, user: User = USER): SessionResponse {
  return {
    success: true,
    authenticated,
    user: authenticated ? user : null,
    providers: { google: false, password: true, ...providers },
  };
}

export function trip(overrides: Partial<TripPayload> = {}): TripPayload {
  return {
    success: true,
    thread_id: "trip_" + "a".repeat(32),
    status: "awaiting_approval",
    user_query: "Plan a 3-day Lisbon trip from Dhaka",
    answer: "",
    itinerary: "## Day 1\n\n- Arrive in **Lisbon**",
    requires_approval: true,
    approval_request: "Please review the generated draft itinerary.",
    flight_results: "",
    hotel_results: "",
    weather_results: "",
    budget_results: "",
    selected_agents: ["flight_agent", "hotel_agent", "itinerary_agent"],
    supervisor_reasoning: "Full plan requested.",
    guardrail_allowed: true,
    guardrail_reason: "",
    revision_count: 0,
    max_revisions: 2,
    llm_calls: 4,
    ...overrides,
  };
}

/** Controllable promise, to observe UI while an async call is in flight. */
export function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

/** Default API behaviour for a test; individual tests override what they care about. */
export function mockApi(authenticated = true, providers: Partial<Providers> = {}) {
  vi.mocked(endpoints.getSession).mockResolvedValue(session(authenticated, providers));
  vi.mocked(endpoints.listTrips).mockResolvedValue([]);
}

export function renderApp(route = "/") {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <App />
    </MemoryRouter>,
  );
}
