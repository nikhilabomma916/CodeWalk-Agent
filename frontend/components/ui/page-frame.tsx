import type { ReactNode } from "react";

interface PageFrameProps {
  title: ReactNode;
  /** Shown after the title in the header bar (counts, breadcrumbs). */
  meta?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
}

/** Header bar + scrolling body used by the Projects and History areas. */
export function PageFrame({ title, meta, actions, children }: PageFrameProps) {
  return (
    <div className="flex h-full min-h-0 flex-col bg-surface">
      <header className="flex h-10 shrink-0 items-center gap-2 border-b border-border bg-surface-sunken px-3">
        <h1 className="min-w-0 truncate text-[11px] font-semibold tracking-wider text-fg-muted uppercase">
          {title}
        </h1>
        {meta && <div className="min-w-0 truncate text-xs text-fg-muted">{meta}</div>}
        <span className="flex-1" />
        {actions && <div className="flex shrink-0 items-center gap-1">{actions}</div>}
      </header>
      <div className="min-h-0 flex-1 overflow-auto">{children}</div>
    </div>
  );
}

export const buttonClass = {
  primary:
    "inline-flex items-center gap-1.5 rounded bg-accent px-2.5 py-1 text-xs font-medium text-white hover:bg-accent-strong disabled:opacity-60",
  secondary:
    "inline-flex items-center gap-1.5 rounded border border-border bg-surface-raised px-2.5 py-1 text-xs text-fg hover:border-border-strong hover:bg-surface-hover disabled:opacity-50",
  danger:
    "inline-flex items-center gap-1.5 rounded border border-danger/40 px-2.5 py-1 text-xs text-danger hover:bg-danger/10 disabled:opacity-50",
} as const;
