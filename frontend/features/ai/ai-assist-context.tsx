"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { useWorkspace } from "@/features/workspace/workspace-context";
import {
  analyzeWithAI,
  explainDiagnostic,
  getAIStatus,
  suggestFix,
  type AIAnalysis,
  type AIAnalysisType,
  type AIExplanation,
  type AIFileInput,
  type AIFixSuggestion,
  type AIStatus,
} from "@/services/api/ai";
import { isApiError } from "@/services/api/errors";
import type { Diagnostic } from "@/types/diagnostics";

/** A request's lifecycle. `data` stays visible while a newer request for the same thing runs. */
export type Remote<T> =
  | { state: "idle" }
  | { state: "loading" }
  | { state: "ready"; data: T }
  | { state: "error"; message: string; code?: string };

export type StatusState =
  { state: "loading" } | { state: "ready"; data: AIStatus } | { state: "error"; message: string };

export interface ExplanationState {
  diagnostic: Diagnostic;
  result: Remote<AIExplanation>;
}

export interface FixState {
  path: string;
  diagnostic?: Diagnostic;
  result: Remote<AIFixSuggestion>;
  /** Whether the diff review is shown in the editor area. */
  reviewOpen: boolean;
  /** What the developer decided; a decided suggestion cannot be applied again. */
  decision: "pending" | "applied" | "rejected";
}

export interface ReviewState {
  path: string;
  analysisType: AIAnalysisType;
  result: Remote<AIAnalysis>;
}

interface AIAssistValue {
  status: StatusState;
  refreshStatus(): Promise<void>;
  explanation: ExplanationState | null;
  explain(diagnostic: Diagnostic): Promise<void>;
  closeExplanation(): void;
  fix: FixState | null;
  requestFix(diagnostic: Diagnostic): Promise<void>;
  openReview(): void;
  closeReview(): void;
  rejectFix(): void;
  /** Applies the reviewed suggestion to the editor; false if the file changed since it was made. */
  applyFix(): boolean;
  review: ReviewState | null;
  runReview(path: string, analysisType: AIAnalysisType): Promise<void>;
}

const AIAssistContext = createContext<AIAssistValue | null>(null);

export function errorState(error: unknown, fallback: string): Remote<never> {
  if (isApiError(error)) {
    if (error.kind === "timeout")
      return { state: "error", message: "The AI request timed out. Try again.", code: "timeout" };
    if (error.kind === "network")
      return { state: "error", message: "The CodeWalk backend is not reachable.", code: "network" };
    return { state: "error", message: error.message, code: error.code };
  }
  return { state: "error", message: fallback };
}

export function AIAssistProvider({ children }: { children: ReactNode }) {
  const { state, actions } = useWorkspace();
  const [status, setStatus] = useState<StatusState>({ state: "loading" });
  const [explanation, setExplanation] = useState<ExplanationState | null>(null);
  const [fix, setFix] = useState<FixState | null>(null);
  const [review, setReview] = useState<ReviewState | null>(null);
  const stateRef = useRef(state);
  useEffect(() => {
    stateRef.current = state;
  }, [state]);
  // Only the newest request of each kind may update the UI.
  const tokens = useRef({ explain: 0, fix: 0, review: 0 });

  const refreshStatus = useCallback(async () => {
    try {
      setStatus({ state: "ready", data: await getAIStatus() });
    } catch (error) {
      setStatus({
        state: "error",
        message: isApiError(error) ? error.message : "Unable to read the AI status.",
      });
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    void Promise.resolve().then(() => {
      if (!cancelled) void refreshStatus();
    });
    return () => {
      cancelled = true;
    };
  }, [refreshStatus]);

  // Results belong to one project: clear them when it changes or closes.
  const projectId = state.project?.id;
  const [shownProject, setShownProject] = useState(projectId);
  if (shownProject !== projectId) {
    setShownProject(projectId);
    setExplanation(null);
    setFix(null);
    setReview(null);
  }

  /** The open file's current (possibly unsaved) content and every diagnostic for it. */
  const fileInput = useCallback((path: string): AIFileInput | null => {
    const current = stateRef.current;
    const buffer = current.buffers[path];
    if (!buffer || buffer.status !== "ready") return null;
    const diagnostics = Object.values(current.diagnostics).flatMap((byFile) => byFile[path] ?? []);
    return {
      code: buffer.content,
      filePath: path,
      projectId: current.project?.serverProjectId,
      diagnostics,
    };
  }, []);

  const explain = useCallback(
    async (diagnostic: Diagnostic) => {
      const token = ++tokens.current.explain;
      const input = fileInput(diagnostic.file);
      if (!input) {
        setExplanation({
          diagnostic,
          result: { state: "error", message: "Open the file to explain its problems." },
        });
        return;
      }
      setExplanation({ diagnostic, result: { state: "loading" } });
      try {
        const data = await explainDiagnostic({ ...input, diagnostic });
        if (token === tokens.current.explain)
          setExplanation({ diagnostic, result: { state: "ready", data } });
      } catch (error) {
        if (token === tokens.current.explain)
          setExplanation({ diagnostic, result: errorState(error, "The explanation failed.") });
      }
    },
    [fileInput],
  );

  const requestFix = useCallback(
    async (diagnostic: Diagnostic) => {
      const token = ++tokens.current.fix;
      const input = fileInput(diagnostic.file);
      const base = {
        path: diagnostic.file,
        diagnostic,
        reviewOpen: false,
        decision: "pending" as const,
      };
      if (!input) {
        setFix({ ...base, result: { state: "error", message: "Open the file to fix it." } });
        return;
      }
      setFix({ ...base, result: { state: "loading" } });
      try {
        const data = await suggestFix({ ...input, diagnostic });
        if (token !== tokens.current.fix) return;
        // Show the diff right away when there is something to review.
        setFix({
          ...base,
          reviewOpen: data.status === "suggested",
          result: { state: "ready", data },
        });
        if (data.status === "suggested") actions.activateTab(diagnostic.file);
      } catch (error) {
        if (token === tokens.current.fix)
          setFix({ ...base, result: errorState(error, "The fix suggestion failed.") });
      }
    },
    [actions, fileInput],
  );

  const applyFix = useCallback((): boolean => {
    if (!fix || fix.result.state !== "ready" || fix.decision !== "pending") return false;
    const suggestion = fix.result.data;
    const buffer = stateRef.current.buffers[fix.path];
    // Only apply to exactly the code the suggestion was computed against.
    if (!buffer || buffer.status !== "ready" || buffer.content !== suggestion.original_code)
      return false;
    actions.replaceContent(fix.path, suggestion.suggested_code);
    setFix({ ...fix, reviewOpen: false, decision: "applied" });
    return true;
  }, [actions, fix]);

  const runReview = useCallback(
    async (path: string, analysisType: AIAnalysisType) => {
      const token = ++tokens.current.review;
      const input = fileInput(path);
      if (!input) {
        setReview({
          path,
          analysisType,
          result: { state: "error", message: "Open a file to review it." },
        });
        return;
      }
      setReview({ path, analysisType, result: { state: "loading" } });
      try {
        const data = await analyzeWithAI({ ...input, analysisType });
        if (token === tokens.current.review)
          setReview({ path, analysisType, result: { state: "ready", data } });
      } catch (error) {
        if (token === tokens.current.review)
          setReview({ path, analysisType, result: errorState(error, "The AI review failed.") });
      }
    },
    [fileInput],
  );

  const value = useMemo<AIAssistValue>(
    () => ({
      status,
      refreshStatus,
      explanation,
      explain,
      closeExplanation: () => {
        tokens.current.explain += 1;
        setExplanation(null);
      },
      fix,
      requestFix,
      openReview: () => setFix((current) => (current ? { ...current, reviewOpen: true } : current)),
      closeReview: () =>
        setFix((current) => (current ? { ...current, reviewOpen: false } : current)),
      rejectFix: () =>
        setFix((current) =>
          current ? { ...current, reviewOpen: false, decision: "rejected" } : current,
        ),
      applyFix,
      review,
      runReview,
    }),
    [applyFix, explain, explanation, fix, refreshStatus, requestFix, review, runReview, status],
  );

  return <AIAssistContext.Provider value={value}>{children}</AIAssistContext.Provider>;
}

export function useAIAssist(): AIAssistValue {
  const value = useContext(AIAssistContext);
  if (!value) throw new Error("useAIAssist must be used inside <AIAssistProvider>");
  return value;
}

/** Why AI cannot be used right now, or null when it can. */
export function unavailableReason(status: StatusState): string | null {
  if (status.state === "loading") return null;
  if (status.state === "error") return status.message;
  return status.data.available ? null : (status.data.detail ?? "AI assistance is not available.");
}
