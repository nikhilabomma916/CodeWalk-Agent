import { Suspense, type ReactNode } from "react";

import { RequireAuth } from "@/features/auth/auth-guards";
import { AppShell } from "@/features/shell/app-shell";
import { WorkspaceProviders } from "@/features/workspace/workspace";

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
