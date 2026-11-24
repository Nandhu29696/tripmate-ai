import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, setUnauthorizedHandler } from "./client";
import { streamRequest } from "./stream";
import type { ProgressEvent } from "./types";

const encoder = new TextEncoder();

/** A streaming Response whose body arrives in the given chunks. */
function streamingResponse(chunks: string[], init: ResponseInit = { status: 200 }): Response {
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
  return new Response(body, init);
}

function mockFetch(response: Response) {
  const fetchMock = vi.fn().mockResolvedValue(response);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const RESULT = { type: "result", success: true, thread_id: "trip_1", status: "awaiting_approval" };

afterEach(() => {
  vi.unstubAllGlobals();
  setUnauthorizedHandler(null);
});

describe("streamRequest", () => {
  it("delivers progress events in order, then resolves with the result", async () => {
    const lines = [
      JSON.stringify({ type: "progress", node: "supervisor", label: "Checking your request", state: "start" }),
      JSON.stringify({ type: "progress", node: "supervisor", label: "Checking your request", state: "done" }),
      JSON.stringify({ type: "ping" }),
      JSON.stringify(RESULT),
    ];
    mockFetch(streamingResponse([lines.join("\n") + "\n"]));

    const seen: ProgressEvent[] = [];
    const result = await streamRequest("/api/travel/stream", { message: "hi" }, (event) => seen.push(event));

    expect(seen.map((event) => event.state)).toEqual(["start", "done"]);
    expect(result.thread_id).toBe("trip_1");
  });

  it("reassembles events split across chunks, even mid-line and mid-character", async () => {
    const line = JSON.stringify({ type: "progress", node: "n", label: "Café stage ✓", state: "start" }) + "\n" + JSON.stringify(RESULT);
    const bytes = encoder.encode(line);
    const pieces = [bytes.slice(0, 20), bytes.slice(20, 61), bytes.slice(61)];
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        pieces.forEach((piece) => controller.enqueue(piece));
        controller.close();
      },
    });
    mockFetch(new Response(body, { status: 200 }));

    const seen: ProgressEvent[] = [];
    const result = await streamRequest("/x", {}, (event) => seen.push(event));

    expect(seen[0]?.label).toBe("Café stage ✓");
    expect(result.status).toBe("awaiting_approval"); // last line has no trailing newline
  });

  it("sends the payload as JSON with cookies", async () => {
    const fetchMock = mockFetch(streamingResponse([JSON.stringify(RESULT) + "\n"]));
    await streamRequest("/api/travel/stream", { message: "Tokyo" }, () => undefined);

    const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(path).toBe("/api/travel/stream");
    expect(init.method).toBe("POST");
    expect(init.credentials).toBe("same-origin");
    expect(JSON.parse(String(init.body))).toEqual({ message: "Tokyo" });
  });

  it("turns an in-stream error event into an ApiError with the server's safe message", async () => {
    const error = { type: "error", status: 429, error: "The AI service is busy right now.", retry_after: "7" };
    mockFetch(streamingResponse([JSON.stringify(error) + "\n"]));

    const failure = await streamRequest("/x", {}, () => undefined).catch((e: unknown) => e);
    expect(failure).toBeInstanceOf(ApiError);
    expect((failure as ApiError).message).toBe("The AI service is busy right now.");
    expect((failure as ApiError).status).toBe(429);
    expect((failure as ApiError).retryAfter).toBe(7);
  });

  it("surfaces checks done before the stream opens as ordinary HTTP errors", async () => {
    const response = new Response(JSON.stringify({ success: false, error: "You have reached the planning limit." }), {
      status: 429,
      headers: { "Content-Type": "application/json", "Retry-After": "120" },
    });
    mockFetch(response);

    const failure = (await streamRequest("/x", {}, () => undefined).catch((e: unknown) => e)) as ApiError;
    expect(failure.status).toBe(429);
    expect(failure.retryAfter).toBe(120);
    expect(failure.message).toContain("planning limit");
  });

  it("tells the app to sign the user out when the session is gone", async () => {
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    mockFetch(new Response(JSON.stringify({ success: false, error: "Please sign in to continue.", auth_required: true }), { status: 401 }));

    await streamRequest("/x", {}, () => undefined).catch(() => undefined);
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it("reports an interrupted connection when no result arrives", async () => {
    mockFetch(streamingResponse([JSON.stringify({ type: "progress", node: "a", label: "A", state: "start" }) + "\n"]));
    const failure = (await streamRequest("/x", {}, () => undefined).catch((e: unknown) => e)) as ApiError;
    expect(failure).toBeInstanceOf(ApiError);
    expect(failure.message).toMatch(/interrupted/i);
  });

  it("ignores malformed lines instead of crashing", async () => {
    mockFetch(streamingResponse(["not json\n", JSON.stringify(RESULT) + "\n"]));
    const result = await streamRequest("/x", {}, () => undefined);
    expect(result.thread_id).toBe("trip_1");
  });
});
