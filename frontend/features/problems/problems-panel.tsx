"use client";

import { useMemo } from "react";

import type { FileAnalysis } from "@/features/workspace/state";
import { useWorkspace } from "@/features/workspace/workspace-context";
import type { AnalysisCapability } from "@/services/api/analysis";
import { SEVERITY_ORDER, type Diagnostic } from "@/types/diagnostics";

import { ProblemsList } from "./problems-list";

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

const CAPABILITY_MARK: Record<AnalysisCapability["status"], string> = {
  performed: "✓",
  skipped: "skipped",
  unavailable: "unavailable",
  not_supported: "—",
};

/** One line stating exactly what was analyzed for the active file. */
export function describeAnalysis(analysis: FileAnalysis | undefined): string {
  if (!analysis) return "Not analyzed yet.";
  switch (analysis.status) {
    case "pending":
      return "Waiting for you to pause typing…";
    case "running":
      return "Analyzing…";
    case "unavailable":
      return `Analysis unavailable: ${analysis.message}`;
    case "failed":
      return `Analysis failed: ${analysis.message}`;
    case "done": {
      const performed = analysis.capabilities.some((c) => c.status === "performed");
      if (!performed) return `No analyzer is available for ${analysis.language}.`;
      const parts = analysis.capabilities.map((c) => `${c.kind} ${CAPABILITY_MARK[c.status]}`);
      const errors = analysis.errors.length ? ` · ${analysis.errors.join("; ")}` : "";
      return `${analysis.language}: ${parts.join(" · ")} (${Math.round(analysis.durationMs)} ms)${errors}`;
    }
  }
}

export function ProblemsPanel() {
  const { state, actions } = useWorkspace();
  const { diagnostics, counts } = useAllDiagnostics();
  const active = state.activePath ? state.analysis[state.activePath] : undefined;

  const select = (diagnostic: Diagnostic) =>
    void actions.revealPosition(diagnostic.file, diagnostic.line, diagnostic.column);

  return (
    <section aria-label="Problems" className="flex h-full min-h-0 flex-col">
      <p className="flex shrink-0 flex-wrap gap-x-3 border-b border-border px-3 py-1 text-[11px] text-fg-muted">
        <span>
          {counts.error} errors · {counts.warning} warnings
          {counts.other ? ` · ${counts.other} info/suggestions` : ""}
        </span>
        {state.activePath && (
          <span className="truncate text-fg-subtle" title={describeAnalysis(active)}>
            {describeAnalysis(active)}
          </span>
        )}
      </p>
      {diagnostics.length === 0 ? (
        <p role="status" className="px-3 py-2 text-xs text-fg-muted">
          {state.openPaths.length === 0
            ? "Open a file to analyze it."
            : "No problems reported for open files."}
        </p>
      ) : (
        <ProblemsList diagnostics={diagnostics} onSelect={select} />
      )}
    </section>
  );
}
