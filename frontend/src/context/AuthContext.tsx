import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { setUnauthorizedHandler } from "../api/client";
import * as endpoints from "../api/endpoints";
import type { Providers, User } from "../api/types";

type AuthStatus = "loading" | "authenticated" | "anonymous" | "error";

interface AuthValue {
  status: AuthStatus;
  user: User | null;
  providers: Providers;
  refresh: () => Promise<void>;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (email: string, password: string, name: string) => Promise<string>;
  signOut: () => Promise<void>;
  removeAccount: () => Promise<void>;
}

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [user, setUser] = useState<User | null>(null);
  const [providers, setProviders] = useState<Providers>({ google: false, password: true });

  const refresh = useCallback(async () => {
    try {
      const session = await endpoints.getSession();
      setProviders(session.providers);
      setUser(session.user);
      setStatus(session.authenticated ? "authenticated" : "anonymous");
    } catch {
      setStatus("error");
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Any 401 from the API (expired or revoked session) drops the user back to the sign-in page.
  useEffect(() => {
    setUnauthorizedHandler(() => {
      setUser(null);
      setStatus((current) => (current === "loading" ? current : "anonymous"));
    });
    return () => setUnauthorizedHandler(null);
  }, []);

  const signIn = useCallback(
    async (email: string, password: string) => {
      await endpoints.login(email, password);
      await refresh();
    },
    [refresh],
  );

  const signUp = useCallback(async (email: string, password: string, name: string) => {
    const result = await endpoints.register(email, password, name);
    return result.message;
  }, []);

  const signOut = useCallback(async () => {
    try {
      await endpoints.logout();
    } finally {
      setUser(null);
      setStatus("anonymous");
    }
  }, []);

  const removeAccount = useCallback(async () => {
    await endpoints.deleteAccount();
    setUser(null);
    setStatus("anonymous");
  }, []);

  const value = useMemo<AuthValue>(
    () => ({ status, user, providers, refresh, signIn, signUp, signOut, removeAccount }),
    [status, user, providers, refresh, signIn, signUp, signOut, removeAccount],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside <AuthProvider>");
  return value;
}
