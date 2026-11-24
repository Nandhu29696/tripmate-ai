import { useCallback, useState } from "react";
import type { ProgressEvent } from "../api/types";

export interface RunStep {
  node: string;
  label: string;
  state: ProgressEvent["state"];
}

/** Accumulates streamed progress events into an ordered list of steps. */
export function useProgress() {
  const [steps, setSteps] = useState<RunStep[]>([]);

  const onProgress = useCallback((event: ProgressEvent) => {
    setSteps((current) => {
      const index = current.findIndex((step) => step.node === event.node);
      if (index < 0) return [...current, { node: event.node, label: event.label, state: event.state }];

      const next = [...current];
      const existing = current[index];
      if (existing) {
        // Keep the label from the "start" event: a revision's finish event would otherwise
        // flip "Revising your itinerary" back to "Drafting your itinerary".
        next[index] = { ...existing, state: event.state, label: event.state === "start" ? event.label : existing.label };
      }
      return next;
    });
  }, []);

  const reset = useCallback(() => setSteps([]), []);

  return { steps, onProgress, reset };
}
