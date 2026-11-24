import { ApiError, errorFromResponse, notifyUnauthorized } from "./client";
import type { ProgressEvent, TripPayload } from "./types";

interface StreamEvent {
  type: string;
  [key: string]: unknown;
}

/**
 * POST that answers with newline-delimited JSON: zero or more `progress`
 * events, then exactly one `result` or `error`. Checks the server does before
 * opening the stream (401, 400, 404, 409, 429) arrive as ordinary JSON errors.
 */
export async function streamRequest(
  path: string,
  payload: unknown,
  onProgress: (event: ProgressEvent) => void,
  signal?: AbortSignal,
): Promise<TripPayload> {
  const response = await fetch(path, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal,
  });

  if (!response.ok) {
    const error = await errorFromResponse(response);
    if (response.status === 401 && error.authRequired) notifyUnauthorized();
    throw error;
  }

  let result: TripPayload | null = null;

  const handleLine = (line: string): void => {
    if (!line.trim()) return;
    let event: StreamEvent;
    try {
      event = JSON.parse(line) as StreamEvent;
    } catch {
      return;
    }

    if (event.type === "progress") {
      onProgress(event as unknown as ProgressEvent);
    } else if (event.type === "result") {
      result = event as unknown as TripPayload;
    } else if (event.type === "error") {
      const retry = Number(event.retry_after);
      throw new ApiError(String(event.error || "Something went wrong. Please try again."), Number(event.status) || 500, {
        retryAfter: Number.isFinite(retry) && retry > 0 ? retry : undefined,
      });
    }
  };

  if (response.body && typeof response.body.getReader === "function") {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let newline = buffer.indexOf("\n");
      while (newline >= 0) {
        handleLine(buffer.slice(0, newline));
        buffer = buffer.slice(newline + 1);
        newline = buffer.indexOf("\n");
      }
    }
    handleLine(buffer + decoder.decode());
  } else {
    // No streaming support: the same events, delivered at the end.
    (await response.text()).split("\n").forEach(handleLine);
  }

  if (!result) {
    throw new ApiError("The connection was interrupted. If your plan finished, it is saved in your trips.", 0);
  }
  return result;
}
