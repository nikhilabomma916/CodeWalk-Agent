import type { ButtonHTMLAttributes, ReactNode } from "react";

interface IconButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "aria-label"> {
  /** Accessible name; also shown as the tooltip. */
  label: string;
  /** Keyboard shortcut appended to the tooltip, e.g. "Ctrl+S". */
  shortcut?: string;
  active?: boolean;
  children: ReactNode;
}

export function IconButton({
  label,
  shortcut,
  active,
  className = "",
  children,
  ...rest
}: IconButtonProps) {
  return (
    <button
      type="button"
      aria-label={label}
      title={shortcut ? `${label} (${shortcut})` : label}
      aria-pressed={active}
      className={`inline-flex h-7 min-w-7 items-center justify-center gap-1 rounded px-1.5 text-fg-muted hover:bg-surface-hover hover:text-fg disabled:pointer-events-none disabled:opacity-40 ${active ? "bg-surface-hover text-fg" : ""} ${className}`}
      {...rest}
    >
      {children}
    </button>
  );
}
