"use client";

import { AlertTriangle, CircleX, Info, Lightbulb } from "lucide-react";
import { memo } from "react";

import type { Diagnostic, DiagnosticSeverity } from "@/types/diagnostics";

export const SEVERITY_VIEW: Record<
  DiagnosticSeverity,
  { icon: typeof CircleX; className: string; label: string }
> = {
  error: { icon: CircleX, className: "text-danger", label: "Error" },
  warning: { icon: AlertTriangle, className: "text-warning", label: "Warning" },
  information: { icon: Info, className: "text-info", label: "Information" },
  suggestion: { icon: Lightbulb, className: "text-fg-muted", label: "Suggestion" },
};

const ProblemRow = memo(function ProblemRow({
  diagnostic,
  onSelect,
}: {
  diagnostic: Diagnostic;
  onSelect(diagnostic: Diagnostic): void;
}) {
  const severity = SEVERITY_VIEW[diagnostic.severity];
  const Icon = severity.icon;
  return (
    <li>
      <button
        type="button"
        onClick={() => onSelect(diagnostic)}
        aria-label={`${severity.label}: ${diagnostic.message} at ${diagnostic.file} line ${diagnostic.line}, column ${diagnostic.column}`}
        className="flex w-full items-start gap-2 px-3 py-1 text-left text-xs hover:bg-surface-hover"
      >
        <Icon aria-hidden className={`mt-px size-3.5 shrink-0 ${severity.className}`} />
        <span className="min-w-0 flex-1">
          <span className="text-fg">{diagnostic.message}</span>
          {diagnostic.suggestedAction && (
            <span className="block text-fg-muted">Fix: {diagnostic.suggestedAction}</span>
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

interface ProblemsListProps {
  diagnostics: readonly Diagnostic[];
  onSelect(diagnostic: Diagnostic): void;
}

export function ProblemsList({ diagnostics, onSelect }: ProblemsListProps) {
  return (
    <ul aria-label="Problems list" className="min-h-0 flex-1 overflow-auto py-1">
      {diagnostics.map((diagnostic) => (
        <ProblemRow
          key={`${diagnostic.file}:${diagnostic.id}`}
          diagnostic={diagnostic}
          onSelect={onSelect}
        />
      ))}
    </ul>
  );
}
