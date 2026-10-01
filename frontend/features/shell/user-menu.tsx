"use client";

import { LogOut } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

import { useAuth } from "@/features/auth/auth-context";
import { useWorkspace } from "@/features/workspace/workspace-context";

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  const letters = parts.length > 1 ? [parts[0][0], parts[parts.length - 1][0]] : [name.trim()[0]];
  return letters.join("").toUpperCase() || "?";
}

function formatDate(value: string | null): string {
  return value ? new Date(value).toLocaleString() : "—";
}

/** Account summary and sign-out. Shows only the user's own non-sensitive details. */
export function UserMenu() {
  const { user, logout } = useAuth();
  const { actions } = useWorkspace();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const firstItemRef = useRef<HTMLButtonElement>(null);
  const menuId = useId();

  useEffect(() => {
    if (!open) return;
    firstItemRef.current?.focus();
    const onPointerDown = (event: PointerEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        buttonRef.current?.focus();
      }
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  if (!user) return null;

  const signOut = async () => {
    setOpen(false);
    // Closing the project first asks about unsaved changes; cancelling keeps the user signed in.
    if (!(await actions.closeProject())) return;
    setBusy(true);
    await logout();
  };

  return (
    <div ref={containerRef} className="relative md:mt-auto">
      <button
        ref={buttonRef}
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        aria-label={`Account: ${user.name}`}
        title={`${user.name} (${user.email})`}
        disabled={busy}
        onClick={() => setOpen((value) => !value)}
        className="mx-auto flex size-8 items-center justify-center rounded-full border border-border-strong bg-surface-raised text-[11px] font-semibold text-fg hover:border-accent disabled:opacity-50"
      >
        {initials(user.name)}
      </button>

      {open && (
        <div
          id={menuId}
          role="menu"
          aria-label="Account"
          className="absolute top-full right-0 z-50 mt-1 w-64 rounded-md border border-border bg-surface-raised text-xs shadow-xl md:top-auto md:right-auto md:bottom-0 md:left-full md:mt-0 md:ml-2"
        >
          <div className="border-b border-border px-3 py-2.5">
            <p className="truncate text-sm font-medium text-fg">{user.name}</p>
            <p className="truncate text-fg-muted">{user.email}</p>
          </div>
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 border-b border-border px-3 py-2 text-[11px]">
            <dt className="text-fg-subtle">Member since</dt>
            <dd className="text-fg-muted">{new Date(user.created_at).toLocaleDateString()}</dd>
            <dt className="text-fg-subtle">Last sign-in</dt>
            <dd className="text-fg-muted">{formatDate(user.last_login_at)}</dd>
          </dl>
          <button
            ref={firstItemRef}
            type="button"
            role="menuitem"
            onClick={() => void signOut()}
            className="flex w-full items-center gap-2 px-3 py-2 text-left text-fg hover:bg-surface-hover focus-visible:bg-surface-hover"
          >
            <LogOut aria-hidden className="size-3.5" />
            Sign out
          </button>
        </div>
      )}
    </div>
  );
}
