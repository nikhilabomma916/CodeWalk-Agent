"use client";

import { AlertTriangle, CircleX, Info, Lightbulb, X } from "lucide-react";
import { memo, useMemo } from "react";

import { IconButton } from "@/components/ui/icon-button";
import { useWorkspace } from "@/features/workspace/workspace-context";
import { SEVERITY_ORDER, type Diagnostic, type DiagnosticSeverity } from "@/types/diagnostics";

const SEVERITY_ICON: Record<
  DiagnosticSeverity,
  { icon: typeof CircleX; className: string; label: string }
> = {
  error: { icon: CircleX, className: "text-danger", label: "Error" },
  warning: { icon: AlertTriangle, className: "text-warning", label: "Warning" },
  info: { icon: Info, className: "text-info", label: "Info" },
  hint: { icon: Lightbulb, className: "text-fg-muted", label: "Hint" },
};

export interface DiagnosticCounts {
  error: number;
  warning: number;
  other: number;
}

/** All diagnostics from every producer, sorted by file, severity, then position. */
export function useAllDiagnostics(): { diagnostics: Diagnostic[]; counts: DiagnosticCounts } {
  const { state } = useWorkspace();
  return useMemo(() => {
    const diagnostics = Object.values(state.diagnostics)
      .flatMap((byFile) => Object.values(byFile).flat())
      .sort(
        (a, b) =>
          a.file.localeCompare(b.file) ||
          SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity] ||
          a.line - b.line ||
          a.column - b.column,
      );
    const counts: DiagnosticCounts = { error: 0, warning: 0, other: 0 };
    for (const diagnostic of diagnostics) {
      if (diagnostic.severity === "error") counts.error += 1;
      else if (diagnostic.severity === "warning") counts.warning += 1;
      else counts.other += 1;
    }
    return { diagnostics, counts };
  }, [state.diagnostics]);
}

const ProblemRow = memo(function ProblemRow({
  diagnostic,
  onSelect,
}: {
  diagnostic: Diagnostic;
  onSelect(diagnostic: Diagnostic): void;
}) {
  const severity = SEVERITY_ICON[diagnostic.severity];
  const Icon = severity.icon;
  return (
    <li>
      <button
        type="button"
        onClick={() => onSelect(diagnostic)}
        className="flex w-full items-start gap-2 px-3 py-1 text-left text-xs hover:bg-surface-hover"
      >
        <Icon
          aria-label={severity.label}
          className={`mt-px size-3.5 shrink-0 ${severity.className}`}
        />
        <span className="min-w-0 flex-1">
          <span className="text-fg">{diagnostic.message}</span>
          {diagnostic.suggestedAction && (
            <span className="block text-fg-muted">{diagnostic.suggestedAction}</span>
          )}
        </span>
        <span className="shrink-0 text-fg-subtle">
          {diagnostic.source}
          {diagnostic.code ? `(${diagnostic.code})` : ""}
        </span>
        <span className="shrink-0 font-mono text-fg-muted">
          {diagnostic.file}:{diagnostic.line}:{diagnostic.column}
        </span>
      </button>
    </li>
  );
});

export function ProblemsPanel({ onClose }: { onClose(): void }) {
  const { actions } = useWorkspace();
  const { diagnostics, counts } = useAllDiagnostics();

  const select = (diagnostic: Diagnostic) =>
    void actions.revealPosition(diagnostic.file, diagnostic.line, diagnostic.column);

  return (
    <section aria-label="Problems" className="flex h-full min-h-0 flex-col bg-surface-sunken">
      <header className="flex h-8 shrink-0 items-center gap-3 border-b border-border pr-1 pl-3">
        <h2 className="text-[11px] font-semibold tracking-wider text-fg uppercase">Problems</h2>
        <span className="text-[11px] text-fg-muted">
          {counts.error} errors · {counts.warning} warnings
          {counts.other ? ` · ${counts.other} other` : ""}
        </span>
        <span className="flex-1" />
        <IconButton label="Close panel" shortcut="Ctrl+J" onClick={onClose}>
          <X aria-hidden className="size-4" />
        </IconButton>
      </header>
      {diagnostics.length === 0 ? (
        <p role="status" className="px-3 py-2 text-xs text-fg-muted">
          No problems reported. Problems currently come from the editor&apos;s built-in syntax
          checking of open files.
        </p>
      ) : (
        <ul className="min-h-0 flex-1 overflow-auto py-1">
          {diagnostics.map((diagnostic) => (
            <ProblemRow key={diagnostic.id} diagnostic={diagnostic} onSelect={select} />
          ))}
        </ul>
      )}
    </section>
  );
}
