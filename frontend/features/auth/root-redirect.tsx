"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { StateMessage } from "@/components/ui/state-message";

import { useAuth } from "./auth-context";
import { DEFAULT_APP_PATH } from "./redirects";

/** `/`: signed-in users go to the app, everyone else to the sign-in page. */
export function RootRedirect() {
  const { status, error, refresh } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (status === "authenticated") router.replace(DEFAULT_APP_PATH);
    else if (status === "unauthenticated") router.replace("/login");
  }, [router, status]);

  if (status === "error") {
    return (
      <StateMessage
        tone="error"
        title="Unable to load CodeWalk"
        action={
          <button
            type="button"
            onClick={() => void refresh()}
            className="mt-1 rounded border border-border px-3 py-1.5 text-xs text-fg hover:bg-surface-hover"
          >
            Try again
          </button>
        }
      >
        {error}
      </StateMessage>
    );
  }
  return <StateMessage title="Loading…" />;
}
