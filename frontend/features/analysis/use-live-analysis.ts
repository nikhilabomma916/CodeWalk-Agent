"use client";

import { useEffect, useRef } from "react";

import type { FileBuffer } from "@/features/workspace/state";
import { ANALYSIS_SOURCE } from "@/features/workspace/state";
import type { WorkspaceActions } from "@/features/workspace/workspace-context";
import { analyzeCode } from "@/services/api/analysis";
import { isApiError } from "@/services/api/errors";

import { analysisLanguageFor } from "./analysis-language";
import { LiveAnalysisScheduler } from "./live-analysis";

/**
 * Runs backend analysis for the active file whenever its content or language
 * changes. Results go to the workspace diagnostics (Problems panel + editor markers).
 */
export function useLiveAnalysis(
  path: string | null,
  buffer: FileBuffer | undefined,
  actions: WorkspaceActions,
): void {
  const scheduler = useRef<LiveAnalysisScheduler | null>(null);

  useEffect(() => {
    const instance = new LiveAnalysisScheduler(
      (request, signal) =>
        analyzeCode(
          { code: request.content, filePath: request.path, language: request.language },
          { signal },
        ),
      {
        onPending: (file) => actions.setAnalysis(file, { status: "pending" }),
        onStart: (file) => actions.setAnalysis(file, { status: "running" }),
        onResult: (file, outcome) => {
          actions.replaceDiagnostics(ANALYSIS_SOURCE, file, outcome.diagnostics);
          actions.setAnalysis(file, {
            status: "done",
            language: outcome.language,
            success: outcome.success,
            capabilities: outcome.capabilities,
            errors: outcome.errors,
            durationMs: outcome.durationMs,
          });
        },
        onError: (file, error) => {
          // Diagnostics for older content would point at the wrong code: clear them.
          actions.replaceDiagnostics(ANALYSIS_SOURCE, file, []);
          const unreachable =
            isApiError(error) && (error.kind === "network" || error.kind === "timeout");
          const message = isApiError(error) ? error.message : "Analysis failed unexpectedly";
          actions.setAnalysis(file, { status: unreachable ? "unavailable" : "failed", message });
        },
      },
    );
    scheduler.current = instance;
    return () => instance.dispose();
  }, [actions]);

  const ready = buffer?.status === "ready";
  const content = ready ? buffer.content : null;
  const override = buffer?.languageOverride;

  useEffect(() => {
    if (!path || content === null) {
      scheduler.current?.cancel();
      return;
    }
    scheduler.current?.schedule({ path, content, language: analysisLanguageFor(path, override) });
  }, [path, content, override]);
}
