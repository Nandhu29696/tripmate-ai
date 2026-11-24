import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import * as endpoints from "../api/endpoints";
import type { TripSummary } from "../api/types";
import { useAuth } from "./AuthContext";

interface TripsValue {
  trips: TripSummary[];
  loading: boolean;
  refresh: () => Promise<void>;
  remove: (threadId: string) => Promise<void>;
}

const TripsContext = createContext<TripsValue | null>(null);

export function TripsProvider({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  const [trips, setTrips] = useState<TripSummary[]>([]);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setTrips(await endpoints.listTrips());
    } catch {
      /* the list is a convenience; the page itself reports real failures */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (status === "authenticated") void refresh();
    if (status === "anonymous") setTrips([]);
  }, [status, refresh]);

  const remove = useCallback(async (threadId: string) => {
    await endpoints.deleteTrip(threadId);
    setTrips((current) => current.filter((trip) => trip.thread_id !== threadId));
  }, []);

  const value = useMemo(() => ({ trips, loading, refresh, remove }), [trips, loading, refresh, remove]);
  return <TripsContext.Provider value={value}>{children}</TripsContext.Provider>;
}

export function useTrips(): TripsValue {
  const value = useContext(TripsContext);
  if (!value) throw new Error("useTrips must be used inside <TripsProvider>");
  return value;
}
