import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as endpoints from "./api/endpoints";
import { ApiError } from "./api/client";
import type { ProgressEvent, TripPayload } from "./api/types";
import { deferred, mockApi, renderApp, trip } from "./test/fixtures";
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { App } from "./App";

vi.mock("./api/endpoints");

const ID = "trip_" + "a".repeat(32);

function progress(node: string, label: string, state: ProgressEvent["state"]): ProgressEvent {
  return { type: "progress", node, label, state };
}

beforeEach(() => {
  mockApi(true);
});

describe("planning a new trip", () => {
  it("asks for a description before calling the server", async () => {
    const user = userEvent.setup();
    renderApp("/");
    await user.click(await screen.findByRole("button", { name: /Create my draft/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Tell us a little about the trip");
    expect(endpoints.startTrip).not.toHaveBeenCalled();
  });

  it("fills the box from a suggestion and counts characters", async () => {
    const user = userEvent.setup();
    renderApp("/");
    await user.click(await screen.findByRole("button", { name: /Japan in autumn/ }));
    expect((screen.getByLabelText("Describe your trip") as HTMLTextAreaElement).value).toContain("7-day Japan trip");
    expect(screen.getByText(/\/ 4000 characters/)).toBeInTheDocument();
  });

  it("shows live progress while the agents work, then opens the draft", async () => {
    const run = deferred<TripPayload>();
    let report: (event: ProgressEvent) => void = () => undefined;
    vi.mocked(endpoints.startTrip).mockImplementation((_message, onProgress) => {
      report = onProgress;
      return run.promise;
    });
    vi.mocked(endpoints.getTrip).mockRejectedValue(new Error("revalidation failed")); // the first paint must survive this

    const user = userEvent.setup();
    renderApp("/");
    await user.type(await screen.findByLabelText("Describe your trip"), "Lisbon for three days");
    await user.click(screen.getByRole("button", { name: /Create my draft/ }));

    expect(await screen.findByText("Working on your trip")).toBeInTheDocument();
    report(progress("supervisor", "Checking your request", "start"));
    report(progress("supervisor", "Checking your request", "done"));
    report(progress("flight_agent", "Checking flights", "start"));
    report(progress("hotel_agent", "Finding hotels", "start"));

    expect(await screen.findByText("Checking flights")).toBeInTheDocument();
    expect(screen.getByText("Finding hotels")).toBeInTheDocument();
    expect(screen.getByText("Checking your request").closest("li")).toHaveClass("is-done");
    expect(screen.getByText("Checking flights").closest("li")).toHaveClass("is-active");

    run.resolve(trip());
    expect(await screen.findByRole("heading", { name: "Draft itinerary" })).toBeInTheDocument();
    expect(endpoints.startTrip).toHaveBeenCalledWith("Lisbon for three days", expect.any(Function), expect.anything());
    expect(screen.queryByText("Trip not available")).not.toBeInTheDocument();
  });

  it("shows how long to wait when the user hits the planning limit", async () => {
    vi.mocked(endpoints.startTrip).mockRejectedValue(new ApiError("You have reached the planning limit for now.", 429, { retryAfter: 1800 }));
    const user = userEvent.setup();
    renderApp("/");
    await user.type(await screen.findByLabelText("Describe your trip"), "Lisbon");
    await user.click(screen.getByRole("button", { name: /Create my draft/ }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("planning limit");
    expect(alert).toHaveTextContent("30 min");
    expect(screen.getByLabelText("Describe your trip")).toHaveValue("Lisbon"); // nothing typed is lost
  });
});

describe("a trip's review workflow", () => {
  beforeEach(() => {
    vi.mocked(endpoints.getTrip).mockResolvedValue(trip({ thread_id: ID }));
  });

  it("restores the draft and the review panel after a reload", async () => {
    renderApp(`/trips/${ID}`);
    expect(await screen.findByRole("heading", { name: "Draft itinerary" })).toBeInTheDocument();
    expect(screen.getByText("Lisbon", { selector: "strong" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Your review" })).toBeInTheDocument();
    expect(screen.getByText("Needs your review")).toBeInTheDocument();
    expect(screen.getByText("Flights")).toBeInTheDocument();
    expect(screen.getByText("Travel scope checked")).toBeInTheDocument();
    expect(endpoints.getTrip).toHaveBeenCalledWith(ID);
  });

  it("will not request changes without saying what to change", async () => {
    const user = userEvent.setup();
    renderApp(`/trips/${ID}`);
    await user.click(await screen.findByRole("button", { name: "Request changes" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("what you'd like to change");
    expect(endpoints.reviewTrip).not.toHaveBeenCalled();
  });

  it("sends feedback, shows a revised draft and counts revisions", async () => {
    vi.mocked(endpoints.reviewTrip).mockImplementation(async (_input, onProgress) => {
      onProgress(progress("itinerary_agent", "Revising your itinerary", "start"));
      return trip({ thread_id: ID, itinerary: "## Revised plan", revision_count: 1 });
    });
    const user = userEvent.setup();
    renderApp(`/trips/${ID}`);

    await user.type(await screen.findByLabelText("Want to change anything?"), "cheaper hotels please");
    await user.click(screen.getByRole("button", { name: "Request changes" }));

    expect(await screen.findByRole("heading", { name: "Revised plan" })).toBeInTheDocument();
    expect(endpoints.reviewTrip).toHaveBeenCalledWith({ thread_id: ID, approved: false, feedback: "cheaper hotels please" }, expect.any(Function), expect.anything());
    expect(screen.getByText("Revision 1 of 2")).toBeInTheDocument();
    expect(screen.getByLabelText("Want to change anything?")).toHaveValue(""); // cleared for the next round
    expect(screen.getByText(/1 revision left/)).toBeInTheDocument();
  });

  it("approves, then shows the final plan without the review panel", async () => {
    vi.mocked(endpoints.reviewTrip).mockResolvedValue(trip({ thread_id: ID, status: "completed", requires_approval: false, answer: "# Final plan\n\nEnjoy Lisbon", itinerary: "" }));
    const user = userEvent.setup();
    renderApp(`/trips/${ID}`);

    await user.click(await screen.findByRole("button", { name: /Looks good, finalize/ }));

    expect(await screen.findByRole("heading", { name: "Your final plan", level: 2 })).toBeInTheDocument();
    expect(screen.getByText("Enjoy Lisbon")).toBeInTheDocument();
    expect(screen.getByText("Final plan ready")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Your review" })).not.toBeInTheDocument();
    expect(endpoints.reviewTrip).toHaveBeenCalledWith({ thread_id: ID, approved: true, feedback: "" }, expect.any(Function), expect.anything());
  });

  it("keeps the draft and shows the reason when the review call fails", async () => {
    vi.mocked(endpoints.reviewTrip).mockRejectedValue(new ApiError("The AI service is busy right now. Please try again shortly.", 429));
    const user = userEvent.setup();
    renderApp(`/trips/${ID}`);
    await user.click(await screen.findByRole("button", { name: /Looks good, finalize/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent("busy right now");
    expect(screen.getByRole("heading", { name: "Draft itinerary" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Looks good, finalize/ })).toBeEnabled();
  });

  it("explains a request outside travel scope instead of showing a plan", async () => {
    vi.mocked(endpoints.getTrip).mockResolvedValue(
      trip({ thread_id: ID, status: "blocked", requires_approval: false, guardrail_allowed: false, answer: "TripMate can only help with travel questions.", itinerary: "" }),
    );
    renderApp(`/trips/${ID}`);
    expect(await screen.findByRole("heading", { name: /outside what TripMate can help with/ })).toBeInTheDocument();
    expect(screen.getByText("TripMate can only help with travel questions.")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Your review" })).not.toBeInTheDocument();
  });

  it("says so when the trip no longer exists", async () => {
    vi.mocked(endpoints.getTrip).mockRejectedValue(new ApiError("Trip not found.", 404));
    renderApp(`/trips/${ID}`);
    expect(await screen.findByRole("heading", { name: "Trip not available" })).toBeInTheDocument();
    expect(screen.getByText(/may have been deleted/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Plan a new trip" })).toBeInTheDocument();
  });

  it("deletes a trip only after confirmation", async () => {
    vi.mocked(endpoints.deleteTrip).mockResolvedValue({ success: true });
    const user = userEvent.setup();
    renderApp(`/trips/${ID}`);

    await user.click(await screen.findByRole("button", { name: "Delete trip" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(endpoints.deleteTrip).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Delete trip" }));
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Delete trip" }));

    await waitFor(() => expect(endpoints.deleteTrip).toHaveBeenCalledWith(ID));
    expect(await screen.findByRole("heading", { name: /Where to next/ })).toBeInTheDocument();
  });

  it("closes the confirmation with Escape", async () => {
    const user = userEvent.setup();
    renderApp(`/trips/${ID}`);
    await user.click(await screen.findByRole("button", { name: "Delete trip" }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });
});

describe("account page", () => {
  it("shows the profile and how the user signs in", async () => {
    renderApp("/account");
    expect(await screen.findByRole("heading", { name: "Account" })).toBeInTheDocument();
    expect(screen.getAllByText("Ada Lovelace").length).toBeGreaterThan(0);
    expect(screen.getByText("Set up")).toBeInTheDocument();
    expect(screen.getByText("Not connected")).toBeInTheDocument();
  });

  it("requires typing DELETE before the account can be deleted", async () => {
    vi.mocked(endpoints.deleteAccount).mockResolvedValue({ success: true, trips_deleted: 0 });
    const user = userEvent.setup();
    renderApp("/account");

    await user.click(await screen.findByRole("button", { name: /Delete my account/ }));
    const dialog = await screen.findByRole("dialog");
    const confirm = within(dialog).getByRole("button", { name: "Delete account" });
    expect(confirm).toBeDisabled();

    await user.type(within(dialog).getByLabelText(/Type/), "delete");
    expect(confirm).toBeDisabled(); // case-sensitive

    await user.clear(within(dialog).getByLabelText(/Type/));
    await user.type(within(dialog).getByLabelText(/Type/), "DELETE");
    expect(confirm).toBeEnabled();
    await user.click(confirm);

    await waitFor(() => expect(endpoints.deleteAccount).toHaveBeenCalled());
    expect(await screen.findByRole("heading", { name: "Welcome back" })).toBeInTheDocument();
  });
});

describe("reloading a trip page", () => {
  const STALE_DRAFT = trip({ thread_id: ID, itinerary: "## Old draft from creation time" });

  function renderWithHandedOverTrip() {
    // Browsers keep navigation state across a reload, so the router can hand back an old trip.
    return render(
      <MemoryRouter initialEntries={[{ pathname: `/trips/${ID}`, state: { trip: STALE_DRAFT } }]}>
        <App />
      </MemoryRouter>,
    );
  }

  it("replaces a stale handed-over draft with the trip's current state", async () => {
    vi.mocked(endpoints.getTrip).mockResolvedValue(trip({ thread_id: ID, status: "completed", requires_approval: false, answer: "# Final plan\n\nApproved version", itinerary: "" }));
    renderWithHandedOverTrip();

    expect(await screen.findByText("Approved version")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Your final plan", level: 2 })).toBeInTheDocument();
    expect(screen.queryByText("Old draft from creation time")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Your review" })).not.toBeInTheDocument();
  });

  it("shows the handed-over trip immediately, before the server answers", async () => {
    const slow = deferred<TripPayload>();
    vi.mocked(endpoints.getTrip).mockReturnValue(slow.promise);
    renderWithHandedOverTrip();

    expect(await screen.findByText("Old draft from creation time")).toBeInTheDocument();
    slow.resolve(STALE_DRAFT);
  });

  it("does not overwrite the result of a review the user already started", async () => {
    const slowFetch = deferred<TripPayload>();
    vi.mocked(endpoints.getTrip).mockReturnValue(slowFetch.promise);
    vi.mocked(endpoints.reviewTrip).mockResolvedValue(trip({ thread_id: ID, status: "completed", requires_approval: false, answer: "# Final plan\n\nFresh result", itinerary: "" }));
    const user = userEvent.setup();
    renderWithHandedOverTrip();

    await user.click(await screen.findByRole("button", { name: /Looks good, finalize/ }));
    expect(await screen.findByText("Fresh result")).toBeInTheDocument();

    slowFetch.resolve(STALE_DRAFT); // the older fetch finally lands
    await waitFor(() => expect(screen.getByText("Fresh result")).toBeInTheDocument());
    expect(screen.queryByText("Old draft from creation time")).not.toBeInTheDocument();
  });
});
