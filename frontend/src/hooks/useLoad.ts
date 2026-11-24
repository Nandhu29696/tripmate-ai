import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../api/client";

export interface Loaded<T> {
  data: T | null;
  error: string;
  loading: boolean;
  reload: () => Promise<void>;
}

/**
 * Loads data when `deps` change and optionally on a timer (paused while the tab is hidden).
 * A slower, older response can never overwrite a newer one.
 */
export function useLoad<T>(load: () => Promise<T>, deps: readonly unknown[], intervalMs = 0): Loaded<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const latest = useRef(0);
  const loader = useRef(load);
  loader.current = load;

  const reload = useCallback(async () => {
    const ticket = ++latest.current;
    try {
      const result = await loader.current();
      if (ticket !== latest.current) return;
      setData(result);
      setError("");
    } catch (caught) {
      if (ticket !== latest.current) return;
      setError(caught instanceof ApiError ? caught.message : "Could not load this. Please try again.");
    } finally {
      if (ticket === latest.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    setLoading(true);
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    if (!intervalMs) return;
    const timer = window.setInterval(() => {
      if (!document.hidden) void reload();
    }, intervalMs);
    return () => window.clearInterval(timer);
  }, [intervalMs, reload]);

  return { data, error, loading, reload };
}
