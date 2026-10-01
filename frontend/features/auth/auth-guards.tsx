"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { StateMessage } from "@/components/ui/state-message";

import { useAuth } from "./auth-context";
import { loginPath, safeNextPath } from "./redirects";

function RetryButton({ onClick }: { onClick(): void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="mt-1 rounded border border-border px-3 py-1.5 text-xs text-fg hover:bg-surface-hover"
    >
      Try again
    </button>
  );
}

/**
 * Renders protected pages only for signed-in users; others are sent to /login
 * with a `next` parameter so they come back after signing in. This is a UX
 * guard only: the backend authorizes every request on its own.
 */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { status, error, refresh, signOutReason } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  useEffect(() => {
    if (status !== "unauthenticated") return;
    if (signOutReason === "user") {
      router.replace(loginPath()); // a deliberate sign-out does not come back here
      return;
    }
    const query = searchParams.toString();
    router.replace(loginPath(`${pathname}${query ? `?${query}` : ""}`));
  }, [pathname, router, searchParams, signOutReason, status]);

  if (status === "authenticated") return <>{children}</>;
  if (status === "error") {
    return (
      <div className="h-dvh">
        <StateMessage
          tone="error"
          title="Unable to load CodeWalk"
          action={<RetryButton onClick={() => void refresh()} />}
        >
          {error}
        </StateMessage>
      </div>
    );
  }
  return (
    <div className="h-dvh">
      <StateMessage title={status === "loading" ? "Checking your session…" : "Redirecting…"} />
    </div>
  );
}

/** For /login and /register: signed-in users go straight to the app (or to `next`). */
export function RedirectIfAuthenticated({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();

  useEffect(() => {
    if (status === "authenticated") router.replace(safeNextPath(searchParams.get("next")));
  }, [router, searchParams, status]);

  if (status === "authenticated") return <StateMessage title="Redirecting…" />;
  return <>{children}</>;
}
