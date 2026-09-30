import type { ReactNode } from "react";

interface StateMessageProps {
  tone?: "neutral" | "error";
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}

/** Shared loading / empty / error placeholder for panels. */
export function StateMessage({ tone = "neutral", title, children, action }: StateMessageProps) {
  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      className="flex h-full flex-col items-center justify-center gap-2 p-6 text-center"
    >
      <p className={`text-sm font-medium ${tone === "error" ? "text-danger" : "text-fg"}`}>
        {title}
      </p>
      {children && <div className="max-w-sm text-xs text-fg-muted">{children}</div>}
      {action}
    </div>
  );
}
