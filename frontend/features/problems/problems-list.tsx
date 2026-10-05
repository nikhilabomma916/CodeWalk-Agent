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
  selected,
  onSelect,
  onExplain,
}: {
  diagnostic: Diagnostic;
  selected: boolean;
  onSelect(diagnostic: Diagnostic): void;
  onExplain?(diagnostic: Diagnostic): void;
}) {
  const severity = SEVERITY_VIEW[diagnostic.severity];
  const Icon = severity.icon;
  return (
    <li className={`group flex items-start ${selected ? "bg-surface-active" : ""}`}>
      <button
        type="button"
        onClick={() => onSelect(diagnostic)}
        aria-label={`${severity.label}: ${diagnostic.message} at ${diagnostic.file} line ${diagnostic.line}, column ${diagnostic.column}`}
        aria-current={selected || undefined}
        className="flex min-w-0 flex-1 items-start gap-2 px-3 py-1 text-left text-xs hover:bg-surface-hover"
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
      {onExplain && (
        <button
          type="button"
          onClick={() => onExplain(diagnostic)}
          aria-label={`Explain with AI: ${diagnostic.message}`}
          className={`mr-1 shrink-0 rounded px-1.5 py-0.5 text-[11px] text-accent-text hover:bg-surface-hover focus-visible:opacity-100 ${
            selected ? "opacity-100" : "opacity-0 group-hover:opacity-100"
          }`}
        >
          Explain
        </button>
      )}
    </li>
  );
});

interface ProblemsListProps {
  diagnostics: readonly Diagnostic[];
  selectedKey?: string | null;
  onSelect(diagnostic: Diagnostic): void;
  /** Offers "Explain with AI" on each problem. */
  onExplain?(diagnostic: Diagnostic): void;
}

export function diagnosticKey(diagnostic: Diagnostic): string {
  return `${diagnostic.file}:${diagnostic.id}`;
}

export function ProblemsList({ diagnostics, selectedKey, onSelect, onExplain }: ProblemsListProps) {
  return (
    <ul aria-label="Problems list" className="min-h-0 flex-1 overflow-auto py-1">
      {diagnostics.map((diagnostic) => (
        <ProblemRow
          key={diagnosticKey(diagnostic)}
          diagnostic={diagnostic}
          selected={selectedKey === diagnosticKey(diagnostic)}
          onSelect={onSelect}
          onExplain={onExplain}
        />
      ))}
    </ul>
  );
}
