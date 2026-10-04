import type { Metadata } from "next";
import { Suspense, type ReactNode } from "react";

import { RequireAuth } from "@/features/auth/auth-guards";
import { AppShell } from "@/features/shell/app-shell";
import { WorkspaceProviders } from "@/features/workspace/workspace";

// Private application pages: never indexed (robots.txt also disallows /app/).
export const metadata: Metadata = { robots: { index: false, follow: false } };

/** Everything under /app requires a signed-in user and shares one workspace state. */
export default function AppLayout({ children }: { children: ReactNode }) {
  return (
    <Suspense>
      <RequireAuth>
        <WorkspaceProviders>
          <AppShell>{children}</AppShell>
        </WorkspaceProviders>
      </RequireAuth>
    </Suspense>
  );
}
