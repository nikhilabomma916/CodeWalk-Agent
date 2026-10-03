"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import * as authApi from "@/services/api/auth";
import type { User } from "@/services/api/auth";
import { onSessionEnded } from "@/services/api/client";
import { isApiError } from "@/services/api/errors";

/**
 * - `loading`: the session has not been checked yet.
 * - `error`: the check failed for a reason other than "not signed in" (e.g. the
 *   backend is down). Protected pages show the problem instead of redirecting,
 *   so a backend outage never looks like a sign-out.
 */
export type AuthStatus = "loading" | "authenticated" | "unauthenticated" | "error";

export interface AuthContextValue {
  status: AuthStatus;
  user: User | null;
  error: string | null;
  /** Why the user is signed out: they chose to, or the backend ended the session (expired or revoked). */
  signOutReason: "user" | "expired" | null;
  /** Shorthand for `signOutReason === "expired"`. */
  sessionExpired: boolean;
  login(input: { email: string; password: string }): Promise<User>;
  register(input: { name: string; email: string; password: string }): Promise<User>;
  logout(): Promise<void>;
  /** Re-reads the current user from the backend. */
  refresh(): Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function describe(error: unknown): string {
  if (isApiError(error)) {
    if (error.kind === "network" || error.kind === "timeout")
      return "The CodeWalk backend is not reachable.";
    return error.message;
  }
  return "Unable to check your session.";
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<{
    status: AuthStatus;
    user: User | null;
    error: string | null;
    signOutReason: "user" | "expired" | null;
  }>({ status: "loading", user: null, error: null, signOutReason: null });
  const statusRef = useRef(state.status);
  useEffect(() => {
    statusRef.current = state.status;
  }, [state.status]);

  const refresh = useCallback(async () => {
    try {
      const user = await authApi.currentUser();
      setState((current) => ({
        ...current,
        status: user ? "authenticated" : "unauthenticated",
        user,
        error: null,
      }));
    } catch (error) {
      setState((current) => ({ ...current, status: "error", user: null, error: describe(error) }));
    }
  }, []);

  useEffect(() => {
    // Defer to a microtask so the effect body does not set state synchronously.
    let cancelled = false;
    void Promise.resolve().then(() => {
      if (!cancelled) void refresh();
    });
    return () => {
      cancelled = true;
    };
  }, [refresh]);

  // Any request rejected with 401 not_authenticated signs the UI out.
  useEffect(
    () =>
      onSessionEnded(() => {
        if (statusRef.current !== "authenticated") return;
        setState({ status: "unauthenticated", user: null, error: null, signOutReason: "expired" });
      }),
    [],
  );

  const login = useCallback(async (input: { email: string; password: string }) => {
    const user = await authApi.login(input);
    setState({ status: "authenticated", user, error: null, signOutReason: null });
    return user;
  }, []);

  const register = useCallback(async (input: { name: string; email: string; password: string }) => {
    const user = await authApi.register(input);
    setState({ status: "authenticated", user, error: null, signOutReason: null });
    return user;
  }, []);

  const logout = useCallback(async () => {
    try {
      await authApi.logout();
    } finally {
      // Even if the request failed, stop presenting the user as signed in.
      setState({ status: "unauthenticated", user: null, error: null, signOutReason: "user" });
    }
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      ...state,
      sessionExpired: state.signOutReason === "expired",
      login,
      register,
      logout,
      refresh,
    }),
    [state, login, register, logout, refresh],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside <AuthProvider>");
  return value;
}
