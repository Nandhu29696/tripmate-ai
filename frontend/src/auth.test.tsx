import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as endpoints from "./api/endpoints";
import { ApiError, notifyUnauthorized } from "./api/client";
import { mockApi, renderApp, session, trip } from "./test/fixtures";

vi.mock("./api/endpoints");

beforeEach(() => {
  vi.mocked(endpoints.logout).mockResolvedValue({ success: true });
});

describe("route protection", () => {
  it("sends a signed-out visitor to the sign-in page", async () => {
    mockApi(false);
    renderApp("/");
    expect(await screen.findByRole("heading", { name: "Welcome back" })).toBeInTheDocument();
    expect(screen.queryByText(/Where to next/)).not.toBeInTheDocument();
  });

  it("returns the visitor to the page they asked for after signing in", async () => {
    mockApi(false);
    const user = userEvent.setup();
    vi.mocked(endpoints.login).mockResolvedValue({ success: true });
    vi.mocked(endpoints.getTrip).mockResolvedValue(trip());
    renderApp("/trips/trip_" + "a".repeat(32));

    await user.type(await screen.findByLabelText("Email"), "ada@example.com");
    await user.type(screen.getByLabelText("Password"), "correct horse battery");
    vi.mocked(endpoints.getSession).mockResolvedValue(session(true)); // the server now knows us
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("heading", { name: "Draft itinerary" })).toBeInTheDocument();
    expect(endpoints.login).toHaveBeenCalledWith("ada@example.com", "correct horse battery");
  });

  it("keeps signed-in visitors off the sign-in page", async () => {
    mockApi(true);
    renderApp("/login");
    expect(await screen.findByRole("heading", { name: /Where to next, Ada/ })).toBeInTheDocument();
  });

  it("signs the user out of the UI when any request reports an expired session", async () => {
    mockApi(true);
    renderApp("/");
    await screen.findByRole("heading", { name: /Where to next/ });

    notifyUnauthorized();

    expect(await screen.findByRole("heading", { name: "Welcome back" })).toBeInTheDocument();
  });

  it("shows a retry screen when the server cannot be reached", async () => {
    vi.mocked(endpoints.getSession).mockRejectedValue(new Error("network"));
    renderApp("/");
    expect(await screen.findByText("We can't reach TripMate right now")).toBeInTheDocument();

    const user = userEvent.setup();
    mockApi(true);
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("heading", { name: /Where to next/ })).toBeInTheDocument();
  });

  it("shows a friendly page for unknown addresses", async () => {
    mockApi(true);
    renderApp("/no/such/page");
    expect(await screen.findByRole("heading", { name: "We took a wrong turn" })).toBeInTheDocument();
  });
});

describe("sign in", () => {
  it("explains a bad password without revealing which part was wrong", async () => {
    mockApi(false);
    vi.mocked(endpoints.login).mockRejectedValue(new ApiError("Invalid email or password.", 401, { authRequired: true }));
    const user = userEvent.setup();
    renderApp("/login");

    await user.type(await screen.findByLabelText("Email"), "ada@example.com");
    await user.type(screen.getByLabelText("Password"), "wrong password!");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid email or password.");
    expect(screen.getByRole("heading", { name: "Welcome back" })).toBeInTheDocument();
  });

  it("asks for both fields before calling the server", async () => {
    mockApi(false);
    const user = userEvent.setup();
    renderApp("/login");
    await user.click(await screen.findByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("enter your email and password");
    expect(endpoints.login).not.toHaveBeenCalled();
  });

  it("tells an unconfirmed user a new confirmation link was sent", async () => {
    mockApi(false);
    vi.mocked(endpoints.login).mockRejectedValue(
      new ApiError("Please confirm your email first. We have sent you a new confirmation link.", 403, { code: "email_not_verified" }),
    );
    const user = userEvent.setup();
    renderApp("/login");

    await user.type(await screen.findByLabelText("Email"), "ada@example.com");
    await user.type(screen.getByLabelText("Password"), "correct horse battery");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("status")).toHaveTextContent("confirm your email first");
  });

  it("reveals and hides the password on request", async () => {
    mockApi(false);
    const user = userEvent.setup();
    renderApp("/login");
    const field = await screen.findByLabelText("Password");
    expect(field).toHaveAttribute("type", "password");
    await user.click(screen.getByRole("button", { name: "Show password" }));
    expect(field).toHaveAttribute("type", "text");
    await user.click(screen.getByRole("button", { name: "Hide password" }));
    expect(field).toHaveAttribute("type", "password");
  });

  it("offers Google only when the server has it configured", async () => {
    mockApi(false, { google: true });
    const first = renderApp("/login");
    const link = await screen.findByRole("link", { name: /Continue with Google/ });
    expect(link).toHaveAttribute("href", "/auth/google/login");
    first.unmount();

    mockApi(false, { google: false });
    renderApp("/login");
    await screen.findByRole("heading", { name: "Welcome back" });
    expect(screen.queryByRole("link", { name: /Continue with Google/ })).not.toBeInTheDocument();
  });
});

describe("create account", () => {
  it("registers and tells the user to check their email", async () => {
    mockApi(false);
    vi.mocked(endpoints.register).mockResolvedValue({ success: true, message: "check" });
    const user = userEvent.setup();
    renderApp("/login?mode=signup");

    await user.type(await screen.findByLabelText("Your name (optional)"), "Ada");
    await user.type(screen.getByLabelText("Email"), "ada@example.com");
    await user.type(screen.getByLabelText("Password"), "correct horse battery");
    await user.click(screen.getByRole("button", { name: "Create account" }));

    expect(await screen.findByRole("heading", { name: "Check your email" })).toBeInTheDocument();
    expect(screen.getByText("ada@example.com")).toBeInTheDocument();
    expect(endpoints.register).toHaveBeenCalledWith("ada@example.com", "correct horse battery", "Ada");
  });

  it("shows the server's reason when the password is rejected", async () => {
    mockApi(false);
    vi.mocked(endpoints.register).mockRejectedValue(new ApiError("That password is too easy to guess. Please choose another.", 400));
    const user = userEvent.setup();
    renderApp("/login?mode=signup");

    await user.type(await screen.findByLabelText("Email"), "ada@example.com");
    await user.type(screen.getByLabelText("Password"), "password123");
    await user.click(screen.getByRole("button", { name: "Create account" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("too easy to guess");
  });

  it("shows a live password-strength meter while typing", async () => {
    mockApi(false);
    const user = userEvent.setup();
    renderApp("/login?mode=signup");
    await user.type(await screen.findByLabelText("Password"), "correct horse battery staple");
    expect(await screen.findByText("Strong")).toBeInTheDocument();
  });

  it("switches between the two modes with the tabs", async () => {
    mockApi(false);
    const user = userEvent.setup();
    renderApp("/login");
    await user.click(await screen.findByRole("tab", { name: "Create account" }));
    expect(screen.getByRole("heading", { name: "Create your account" })).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "Sign in" }));
    expect(screen.getByRole("heading", { name: "Welcome back" })).toBeInTheDocument();
  });
});

describe("forgot and reset password", () => {
  it("always shows the same confirmation, whatever the address", async () => {
    mockApi(false);
    vi.mocked(endpoints.forgotPassword).mockResolvedValue({ success: true, message: "If an account exists for that address, we have sent a link." });
    const user = userEvent.setup();
    renderApp("/forgot");

    await user.type(await screen.findByLabelText("Email"), "anyone@example.com");
    await user.click(screen.getByRole("button", { name: "Send reset link" }));

    expect(await screen.findByRole("heading", { name: "Check your email" })).toBeInTheDocument();
    expect(screen.getByText(/If an account exists/)).toBeInTheDocument();
  });

  it("rejects a reset page opened without a token", async () => {
    mockApi(false);
    renderApp("/reset");
    expect(await screen.findByRole("heading", { name: "This link isn't valid" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Request a new link" })).toHaveAttribute("href", "/forgot");
  });

  it("sets the new password and signs the user in", async () => {
    mockApi(false);
    vi.mocked(endpoints.resetPassword).mockResolvedValue({ success: true });
    const user = userEvent.setup();
    renderApp("/reset?token=tok_123456789012");

    await user.type(await screen.findByLabelText("New password"), "a brand new passphrase");
    vi.mocked(endpoints.getSession).mockResolvedValue(session(true));
    await user.click(screen.getByRole("button", { name: "Set new password" }));

    expect(await screen.findByRole("heading", { name: /Where to next/ })).toBeInTheDocument();
    expect(endpoints.resetPassword).toHaveBeenCalledWith("tok_123456789012", "a brand new passphrase");
  });

  it("offers a fresh link when the token has expired", async () => {
    mockApi(false);
    vi.mocked(endpoints.resetPassword).mockRejectedValue(new ApiError("This reset link is invalid or has expired. Please request a new one.", 400));
    const user = userEvent.setup();
    renderApp("/reset?token=tok_123456789012");

    await user.type(await screen.findByLabelText("New password"), "a brand new passphrase");
    await user.click(screen.getByRole("button", { name: "Set new password" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("expired");
    expect(screen.getByRole("link", { name: "Request a new link" })).toBeInTheDocument();
  });
});

describe("app shell", () => {
  it("shows who is signed in and lists their trips", async () => {
    mockApi(true);
    vi.mocked(endpoints.listTrips).mockResolvedValue([
      { thread_id: "trip_" + "b".repeat(32), title: "Kyoto in spring", status: "completed", created_at: "2026-11-20T10:00:00Z", updated_at: "2026-11-20T10:05:00Z" },
    ]);
    renderApp("/");

    expect(await screen.findByText("Kyoto in spring")).toBeInTheDocument();
    expect(screen.getByText("Final plan ready")).toBeInTheDocument();
    expect(screen.getAllByText("Ada Lovelace").length).toBeGreaterThan(0);
    expect(screen.getByText("ada@example.com")).toBeInTheDocument();
  });

  it("signs out and returns to the sign-in page", async () => {
    mockApi(true);
    const user = userEvent.setup();
    renderApp("/");
    await screen.findByRole("heading", { name: /Where to next/ });

    await user.click(screen.getByRole("button", { name: /Sign out/ }));

    expect(await screen.findByRole("heading", { name: "Welcome back" })).toBeInTheDocument();
    expect(endpoints.logout).toHaveBeenCalled();
    await waitFor(() => expect(screen.queryByText("ada@example.com")).not.toBeInTheDocument());
  });

  it("switches theme and remembers the choice", async () => {
    mockApi(true);
    const user = userEvent.setup();
    renderApp("/");
    await screen.findByRole("heading", { name: /Where to next/ });

    await user.click(screen.getByRole("button", { name: /Switch to dark theme/ }));
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(window.localStorage.getItem("tripmate-theme")).toBe("dark");
  });
});
