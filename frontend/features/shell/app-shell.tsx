"use client";

import { Code2, FolderKanban, History } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { LogoMark } from "@/components/ui/logo";

import { UserMenu } from "./user-menu";

export const NAV_ITEMS = [
  { href: "/app/coding", label: "Coding", icon: Code2 },
  { href: "/app/projects", label: "Projects", icon: FolderKanban },
  { href: "/app/history", label: "History", icon: History },
] as const;

export function isActivePath(pathname: string, href: string): boolean {
  return pathname === href || pathname.startsWith(`${href}/`);
}

/**
 * The signed-in application frame: a narrow navigation rail on the left
 * (a top bar on small screens) and the active area on the right.
 */
export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();

  return (
    <div className="flex h-dvh min-h-0 flex-col md:flex-row">
      <nav
        aria-label="Main"
        className="flex shrink-0 items-center gap-1 border-b border-border bg-surface-sunken px-2 md:w-16 md:flex-col md:items-stretch md:border-r md:border-b-0 md:px-1.5 md:py-2"
      >
        <Link
          href="/app/projects"
          className="flex h-10 items-center justify-center gap-2 pr-2 md:mb-2 md:h-9 md:pr-0"
          title="CodeWalk Agent"
        >
          <LogoMark />
          <span className="text-sm font-semibold tracking-tight text-fg md:sr-only">CodeWalk</span>
        </Link>

        <ul className="flex flex-1 items-center gap-0.5 md:flex-col md:items-stretch md:gap-1">
          {NAV_ITEMS.map(({ href, label, icon: Icon }) => {
            const active = isActivePath(pathname, href);
            return (
              <li key={href}>
                <Link
                  href={href}
                  aria-current={active ? "page" : undefined}
                  className={`relative flex h-8 items-center gap-1.5 rounded px-2 text-xs md:h-auto md:flex-col md:gap-0.5 md:px-0 md:py-1.5 md:text-[10px] ${
                    active
                      ? "bg-surface-active text-fg"
                      : "text-fg-muted hover:bg-surface-hover hover:text-fg"
                  }`}
                >
                  {active && (
                    <span
                      aria-hidden
                      className="absolute inset-x-1 bottom-0 h-0.5 rounded bg-accent md:inset-x-auto md:inset-y-1 md:left-0 md:h-auto md:w-0.5"
                    />
                  )}
                  <Icon aria-hidden className="size-4 md:size-5" />
                  <span>{label}</span>
                </Link>
              </li>
            );
          })}
        </ul>

        <UserMenu />
      </nav>

      <div className="min-h-0 min-w-0 flex-1">{children}</div>
    </div>
  );
}
