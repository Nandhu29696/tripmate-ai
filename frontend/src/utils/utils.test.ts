import { describe, expect, it, vi } from "vitest";
import { firstName, initials, passwordStrength, returnPath, timeAgo } from "./format";
import { bootstrapUrl, takeFlash } from "./urlParams";

function run(url: string) {
  const parsed = new URL(url, "http://localhost");
  const history = { replaceState: vi.fn() } as unknown as History;
  bootstrapUrl({ pathname: parsed.pathname, search: parsed.search } as Location, history);
  return history.replaceState as unknown as ReturnType<typeof vi.fn>;
}

describe("bootstrapUrl", () => {
  it("rewrites an emailed reset link to the reset page and keeps the token intact", () => {
    const replace = run("/?reset=abc_DEF-123");
    expect(replace).toHaveBeenCalledWith(null, "", "/reset?token=abc_DEF-123");
    expect(takeFlash()).toBeNull();
  });

  it("encodes unusual token characters", () => {
    expect(run("/?reset=a%26b").mock.calls[0]?.[2]).toBe("/reset?token=a%26b");
  });

  it("remembers a success message once and cleans the address bar after email confirmation", () => {
    const replace = run("/?verified=1");
    expect(replace).toHaveBeenCalledWith(null, "", "/");
    expect(takeFlash()).toEqual({ kind: "success", message: expect.stringContaining("confirmed") });
    expect(takeFlash()).toBeNull();
  });

  it.each([
    ["google_failed", "did not work"],
    ["google_denied", "cancelled"],
    ["invalid_link", "expired"],
  ])("maps auth_error=%s to a readable message", (code, text) => {
    run(`/?auth_error=${code}`);
    const flash = takeFlash();
    expect(flash?.kind).toBe("error");
    expect(flash?.message).toContain(text);
  });

  it("falls back to a generic message for unknown error codes", () => {
    run("/?auth_error=something_new");
    expect(takeFlash()?.message).toBeTruthy();
  });

  it("leaves other pages and unrelated query strings alone", () => {
    expect(run("/trips/abc?x=1")).not.toHaveBeenCalled();
    expect(run("/?utm_source=newsletter")).not.toHaveBeenCalled();
    expect(run("/")).not.toHaveBeenCalled();
  });
});

describe("format helpers", () => {
  const now = Date.parse("2026-11-24T12:00:00Z");

  it.each([
    ["2026-11-24T11:59:40Z", "just now"],
    ["2026-11-24T11:30:00Z", "30 min ago"],
    ["2026-11-24T09:00:00Z", "3 h ago"],
    ["2026-11-20T12:00:00Z", "4 d ago"],
  ])("timeAgo(%s) is %s", (iso, expected) => {
    expect(timeAgo(iso, now)).toBe(expected);
  });

  it("timeAgo tolerates bad input", () => {
    expect(timeAgo("not a date", now)).toBe("");
  });

  it("builds names and initials safely", () => {
    expect(firstName("Ada Lovelace")).toBe("Ada");
    expect(firstName("   ")).toBe("there");
    expect(initials("Ada Lovelace")).toBe("AL");
    expect(initials("madonna")).toBe("M");
    expect(initials("")).toBe("?");
  });

  it("scores passwords consistently with the server's 10-character minimum", () => {
    expect(passwordStrength("")).toBe(0);
    expect(passwordStrength("correct")).toBe(1); // typing has started: say "Too short"
    expect(passwordStrength("short1A!")).toBeLessThanOrEqual(1);
    expect(passwordStrength("abcdefghij")).toBeGreaterThanOrEqual(1);
    expect(passwordStrength("correct horse battery staple")).toBe(4);
    expect(passwordStrength("Tr0ub4dor&3xyz")).toBeGreaterThanOrEqual(3);
  });
});

describe("returnPath", () => {
  it("returns the page the visitor asked for", () => {
    expect(returnPath({ from: "/trips/trip_abc" })).toBe("/trips/trip_abc");
    expect(returnPath({ from: "/account" })).toBe("/account");
  });

  it.each([
    ["nothing stored", null],
    ["no from", {}],
    ["a full URL", { from: "https://evil.example/phish" }],
    ["a protocol-relative URL", { from: "//evil.example" }],
    ["the sign-in page itself", { from: "/login" }],
    ["a non-string", { from: 42 }],
  ])("falls back to the home page for %s", (_label, state) => {
    expect(returnPath(state)).toBe("/");
  });
});
