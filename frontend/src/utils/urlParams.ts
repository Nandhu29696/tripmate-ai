/**
 * Links from emails and the Google redirect arrive at the site root with a query
 * string (`/?reset=<token>`, `/?verified=1`, `/?auth_error=<code>`). This runs once,
 * before React renders: it rewrites the address bar to a clean URL (so a route guard
 * cannot discard the parameters) and remembers any message to show.
 */

export interface Flash {
  kind: "success" | "error";
  message: string;
}

const AUTH_ERRORS: Record<string, string> = {
  google_failed: "Google sign-in did not work. Please try again.",
  google_denied: "Google sign-in was cancelled.",
  google_not_configured: "Google sign-in is not available right now.",
  invalid_link: "That link is invalid or has expired. Please request a new one.",
};

let pending: Flash | null = null;

export function bootstrapUrl(loc: Location = window.location, history: History = window.history): void {
  if (loc.pathname !== "/" || !loc.search) return;

  const params = new URLSearchParams(loc.search);
  const reset = params.get("reset");
  const authError = params.get("auth_error");

  if (reset) {
    history.replaceState(null, "", `/reset?token=${encodeURIComponent(reset)}`);
    return;
  }

  if (params.get("verified") === "1") {
    pending = { kind: "success", message: "Your email is confirmed. Welcome to TripMate AI!" };
  } else if (authError) {
    pending = { kind: "error", message: AUTH_ERRORS[authError] ?? "That sign-in link did not work." };
  } else {
    return; // unrelated query string: leave it alone
  }

  history.replaceState(null, "", "/");
}

/** Returns the pending message once, then clears it. */
export function takeFlash(): Flash | null {
  const flash = pending;
  pending = null;
  return flash;
}
