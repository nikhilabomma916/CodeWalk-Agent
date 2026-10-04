import { Suspense, type ReactNode } from "react";

import { LogoMark } from "@/components/ui/logo";
import { RedirectIfAuthenticated } from "@/features/auth/auth-guards";
import { ThemeToggle } from "@/features/theme/theme-context";

export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <main className="flex h-dvh overflow-auto bg-app px-4 py-8">
      <div className="m-auto w-full max-w-sm">
        <div className="mb-5 flex items-center gap-2">
          <LogoMark className="size-6" />
          <span className="flex-1 text-sm font-semibold tracking-tight text-fg">
            CodeWalk Agent
          </span>
          <ThemeToggle className="size-8" />
        </div>
        <div className="rounded-md border border-border bg-surface p-5">
          <Suspense>
            <RedirectIfAuthenticated>{children}</RedirectIfAuthenticated>
          </Suspense>
        </div>
        <p className="mt-4 text-[11px] leading-relaxed text-fg-subtle">
          Your session is kept in a secure, http-only cookie. Code you store is analyzed statically
          and never executed.
        </p>
      </div>
    </main>
  );
}
