import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as endpoints from "./api/endpoints";
import type { AdminOverview, AdminUser } from "./api/types";
import { renderApp, session, trip, USER } from "./test/fixtures";

vi.mock("./api/endpoints");

const ADMIN = { ...USER, name: "Ada Admin", email: "ada@example.com", role: "admin" as const };

const OVERVIEW: AdminOverview = {
  users: { total: 3, verified: 2, admins: 1, disabled: 0, new_7d: 1, google: 1 },
  trips: { by_status: { completed: 2, awaiting_approval: 1 }, last_24h: 1, total: 3 },
  requests: {
    hours: 24, total: 120, client_errors: 4, server_errors: 0, avg_ms: 35.2, p95_ms: 410,
    input_tokens: 41200, output_tokens: 9300, llm_calls: 14,
    series: [{ hour: "2026-11-24T10:00:00+00:00", requests: 120, errors: 0 }],
  },
  sql: { count: 50, slow: 1, errors: 0, avg_ms: 2.5, max_ms: 230 },
  ready: { ready: true, database: "ok" },
};

function adminUser(overrides: Partial<AdminUser> = {}): AdminUser {
  return {
    id: "usr_" + "1".repeat(32), email: "bob@example.com", name: "Bob", role: "user", email_verified: true,
    has_password: true, has_google: false, is_active: true, created_at: "2026-11-01T10:00:00Z",
    last_login: "2026-11-23T10:00:00Z", trips: 2, tokens: 12345, ...overrides,
  };
}

function signInAs(role: "user" | "admin") {
  vi.mocked(endpoints.getSession).mockResolvedValue(session(true, {}, role === "admin" ? ADMIN : USER));
  vi.mocked(endpoints.listTrips).mockResolvedValue([]);
}

beforeEach(() => {
  vi.mocked(endpoints.adminOverview).mockResolvedValue({ success: true, ...OVERVIEW });
});

describe("admin access", () => {
  it("does not show the admin link to normal users and sends them home from /admin", async () => {
    signInAs("user");
    renderApp("/admin");
    expect(await screen.findByRole("heading", { name: /Where to next/ })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Admin console/ })).not.toBeInTheDocument();
    expect(endpoints.adminOverview).not.toHaveBeenCalled();
  });

  it("shows the admin link and the overview to administrators", async () => {
    signInAs("admin");
    renderApp("/admin");
    expect(await screen.findByRole("heading", { name: "Admin console" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Admin console/ })).toBeInTheDocument();
    expect(await screen.findByText("120")).toBeInTheDocument(); // requests in 24 h
    expect(screen.getByText("Healthy")).toBeInTheDocument();
    expect(screen.getByText("Final plan ready")).toBeInTheDocument();
  });

  it("shows a retry when the overview cannot load", async () => {
    signInAs("admin");
    vi.mocked(endpoints.adminOverview).mockRejectedValueOnce(new Error("boom"));
    const user = userEvent.setup();
    renderApp("/admin");
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load");
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Healthy")).toBeInTheDocument();
  });
});

describe("user management", () => {
  beforeEach(() => {
    signInAs("admin");
    vi.mocked(endpoints.adminUsers).mockResolvedValue({
      total: 2,
      users: [
        adminUser({ id: "usr_" + "9".repeat(32), email: "ada@example.com", name: "Ada Admin", role: "admin" }),
        adminUser(),
      ],
    });
  });

  it("lists users, marks the signed-in admin as you and offers no actions on yourself", async () => {
    renderApp("/admin/users");
    const rows = await screen.findAllByRole("row");
    const own = rows.find((r) => within(r).queryByText("ada@example.com"));
    expect(own && within(own).getByText("You")).toBeTruthy();
    const bob = rows.find((r) => within(r).queryByText("bob@example.com"));
    expect(bob && within(bob).getByRole("button", { name: "Disable" })).toBeTruthy();
  });

  it("disables a user and reloads the list", async () => {
    vi.mocked(endpoints.adminUpdateUser).mockResolvedValue({ user: adminUser({ is_active: false }) });
    const user = userEvent.setup();
    renderApp("/admin/users");
    const bob = (await screen.findAllByRole("row")).find((r) => within(r).queryByText("bob@example.com"))!;
    await user.click(within(bob).getByRole("button", { name: "Disable" }));
    await waitFor(() => expect(endpoints.adminUpdateUser).toHaveBeenCalledWith("usr_" + "1".repeat(32), { is_active: false }));
    await waitFor(() => expect(endpoints.adminUsers).toHaveBeenCalledTimes(2));
  });

  it("promotes only users with a verified email", async () => {
    vi.mocked(endpoints.adminUsers).mockResolvedValue({ total: 1, users: [adminUser({ email_verified: false })] });
    renderApp("/admin/users");
    const row = (await screen.findAllByRole("row")).find((r) => within(r).queryByText("bob@example.com"))!;
    expect(within(row).getByRole("button", { name: "Make admin" })).toBeDisabled();
    expect(within(row).getByText("Unverified")).toBeInTheDocument();
  });

  it("asks before deleting a user and names the consequences", async () => {
    vi.mocked(endpoints.adminDeleteUser).mockResolvedValue({ trips_deleted: 2 });
    const user = userEvent.setup();
    renderApp("/admin/users");
    await user.click(await screen.findByRole("button", { name: "Delete bob@example.com" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("bob@example.com");
    expect(dialog).toHaveTextContent("all of their trips (2)");
    expect(endpoints.adminDeleteUser).not.toHaveBeenCalled();
    await user.click(within(dialog).getByRole("button", { name: "Delete user" }));
    await waitFor(() => expect(endpoints.adminDeleteUser).toHaveBeenCalledWith("usr_" + "1".repeat(32)));
  });

  it("searches by name or email", async () => {
    const user = userEvent.setup();
    renderApp("/admin/users");
    await user.type(await screen.findByRole("searchbox", { name: "Search users" }), "bob");
    await waitFor(() => expect(endpoints.adminUsers).toHaveBeenLastCalledWith({ q: "bob", limit: 25, offset: 0 }));
  });
});

describe("logs", () => {
  beforeEach(() => {
    signInAs("admin");
    vi.mocked(endpoints.adminRequestLogs).mockResolvedValue({
      logs: [
        { id: 2, ts: "2026-11-24T10:00:01Z", request_id: "abc123def456", method: "POST", path: "/api/travel/stream", status: 500, duration_ms: 1520, user_id: "usr_" + "1".repeat(32), ip: "10.0.0.1", input_tokens: 8200, output_tokens: 3100, llm_calls: 5 },
        { id: 1, ts: "2026-11-24T10:00:00Z", request_id: "fff000fff000", method: "GET", path: "/api/session", status: 200, duration_ms: 3, user_id: null, ip: "10.0.0.2", input_tokens: 0, output_tokens: 0, llm_calls: 0 },
      ],
    });
    vi.mocked(endpoints.adminSqlLogs).mockResolvedValue({
      enabled: true, slow_threshold_ms: 200, summary: { count: 2, slow: 1, errors: 0, avg_ms: 100, max_ms: 230 },
      logs: [{ id: 1, ts: "2026-11-24T10:00:00Z", sql: "SELECT * FROM users WHERE id = %s", duration_ms: 230, rows: 1, error: "", request_id: "abc123def456", slow: true }],
    });
    vi.mocked(endpoints.adminAuditLogs).mockResolvedValue({
      logs: [{ id: 1, ts: "2026-11-24T10:00:00Z", actor_id: "u", actor_email: "ada@example.com", action: "user.update", target: "bob@example.com", detail: "disabled", ip: "10.0.0.1" }],
    });
  });

  it("shows API requests with status, duration and request id", async () => {
    renderApp("/admin/logs");
    const row = (await screen.findAllByRole("row")).find((r) => within(r).queryByText("/api/travel/stream"))!;
    expect(within(row).getByText("500")).toBeInTheDocument();
    expect(within(row).getByText("1.5 s")).toBeInTheDocument();
    expect(within(row).getByText("abc123def456")).toBeInTheDocument();
  });

  it("filters requests by status and passes the filter to the server", async () => {
    const user = userEvent.setup();
    renderApp("/admin/logs");
    await screen.findByText("/api/session");
    await user.selectOptions(screen.getByRole("combobox", { name: "Status" }), "5xx");
    await waitFor(() => expect(endpoints.adminRequestLogs).toHaveBeenLastCalledWith(expect.objectContaining({ status: "5xx" })));
  });

  it("shows SQL statements with timing and flags slow ones", async () => {
    const user = userEvent.setup();
    renderApp("/admin/logs");
    await user.click(await screen.findByRole("tab", { name: "SQL queries" }));
    expect(await screen.findByText("SELECT * FROM users WHERE id = %s")).toBeInTheDocument();
    expect(screen.getByText("230 ms")).toHaveClass("is-slow");
    expect(screen.getByText(/never recorded/)).toBeInTheDocument();
  });

  it("shows the audit trail of admin actions", async () => {
    const user = userEvent.setup();
    renderApp("/admin/logs");
    await user.click(await screen.findByRole("tab", { name: "Admin actions" }));
    expect(await screen.findByText("user.update")).toBeInTheDocument();
    expect(screen.getByText("bob@example.com")).toBeInTheDocument();
  });
});

describe("day-wise plan", () => {
  it("renders day cards with weather for a trip in the new layout", async () => {
    signInAs("user");
    const itinerary =
      "## Trip at a glance\n- **Destination:** Lisbon, Portugal\n\n## Day 1 - Alfama\n**Weather:** ☀️ 24 °C, sunny\n- **Morning:** Castle\n- **Est. cost:** ~$80\n\n## Day 2 - Belem\n**Weather:** 🌧️ 17 °C, showers\n- **Morning:** Tower\n";
    vi.mocked(endpoints.getTrip).mockResolvedValue(trip({ itinerary }));
    renderApp("/trips/" + "trip_" + "a".repeat(32));
    expect(await screen.findByRole("article", { name: "Day 1" })).toBeInTheDocument();
    const day2 = screen.getByRole("article", { name: "Day 2" });
    expect(within(day2).getByText(/17 °C, showers/)).toBeInTheDocument();
    expect(screen.getByText("Lisbon, Portugal")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Day 2" })).toBeInTheDocument(); // jump nav
  });

  it("still shows plain text plans that are not in the day layout", async () => {
    signInAs("user");
    vi.mocked(endpoints.getTrip).mockResolvedValue(trip({ itinerary: "## Itinerary\n\n- Arrive in **Lisbon**" }));
    renderApp("/trips/" + "trip_" + "a".repeat(32));
    expect(await screen.findByText("Lisbon")).toBeInTheDocument();
    expect(screen.queryByRole("article", { name: /^Day/ })).not.toBeInTheDocument();
  });
});

describe("token accounting and budget", () => {
  it("shows AI tokens on the overview, per user and per request", async () => {
    signInAs("admin");
    vi.mocked(endpoints.adminUsers).mockResolvedValue({ total: 1, users: [adminUser()] });
    vi.mocked(endpoints.adminRequestLogs).mockResolvedValue({
      logs: [
        { id: 2, ts: "2026-11-24T10:00:01Z", request_id: "abc123def456", method: "POST", path: "/api/travel/stream", status: 200, duration_ms: 14000, user_id: null, ip: "10.0.0.1", input_tokens: 8200, output_tokens: 3100, llm_calls: 5 },
        { id: 1, ts: "2026-11-24T10:00:00Z", request_id: "fff000fff000", method: "GET", path: "/api/session", status: 200, duration_ms: 3, user_id: null, ip: "10.0.0.2", input_tokens: 0, output_tokens: 0, llm_calls: 0 },
      ],
    });

    const overview = renderApp("/admin");
    expect(await screen.findByText("AI tokens (24 h)")).toBeInTheDocument();
    expect(screen.getByText("50.5k")).toBeInTheDocument();
    expect(screen.getByText(/41\.2k in \/ 9\.3k out, 14 AI calls/)).toBeInTheDocument();
    overview.unmount();

    const users = renderApp("/admin/users");
    expect(await screen.findByText("12.3k")).toBeInTheDocument();
    users.unmount();

    renderApp("/admin/logs");
    const rows = await screen.findAllByRole("row");
    const row = rows.find((r) => within(r).queryByText("/api/travel/stream"))!;
    expect(within(row).getByText("11.3k")).toBeInTheDocument();
    expect(within(row).getByText("8.2k in / 3.1k out")).toBeInTheDocument();
    const plain = rows.find((r) => within(r).queryByText("/api/session"))!;
    expect(within(plain).queryByText(/ in \//)).not.toBeInTheDocument();
  });

  it("puts the total trip budget in a prominent banner", async () => {
    signInAs("user");
    const itinerary =
      "## Trip at a glance\n- **Destination:** Goa\n- **Budget:** Mid-range, about ₹60,000 in total\n\n## Day 1 - Beach\n- **Morning:** Swim\n\n## Budget summary\n- **Stay:** ₹20,000\n- **Total:** ₹58,000 - ₹62,000 for 2 travellers\n- **Per person:** ₹29,000 - ₹31,000\n";
    vi.mocked(endpoints.getTrip).mockResolvedValue(trip({ itinerary }));
    renderApp("/trips/" + "trip_" + "a".repeat(32));
    const banner = await screen.findByRole("region", { name: "Estimated total budget" });
    expect(banner).toHaveTextContent("₹58,000 - ₹62,000 for 2 travellers");
    expect(banner).toHaveTextContent("Per person");
    expect(banner).toHaveTextContent("₹29,000 - ₹31,000");
    expect(screen.queryByText(/about ₹60,000/)).not.toBeInTheDocument(); // one total only
  });
});
