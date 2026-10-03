"use client";

import { AlertTriangle, CircleX, Info } from "lucide-react";
import { useState } from "react";

import { useWorkspace } from "@/features/workspace/workspace-context";
import { AI_ANALYSIS_TYPES, type AIAnalysisType, type AIFinding } from "@/services/api/ai";

import { unavailableReason, useAIAssist } from "./ai-assist-context";
import { AdvisoryFooter, ConfidenceLabel, RemoteStatus } from "./ai-common";

export const ANALYSIS_TYPE_LABELS: Record<AIAnalysisType, string> = {
  general_review: "General review",
  bug_detection: "Likely bugs",
  quality_review: "Code quality",
  security_review: "Security",
  performance_review: "Performance",
  explain_code: "Explain code",
};

const SEVERITY_ICON = {
  error: { icon: CircleX, className: "text-danger" },
  warning: { icon: AlertTriangle, className: "text-warning" },
  info: { icon: Info, className: "text-info" },
} as const;

function FindingItem({ finding, onReveal }: { finding: AIFinding; onReveal(line: number): void }) {
  const [open, setOpen] = useState(false);
  const { icon: Icon, className } = SEVERITY_ICON[finding.severity];
  return (
    <li className="border-b border-border/60 last:border-0">
      <div className="flex items-start gap-2 px-3 py-1.5 text-xs">
        <Icon aria-hidden className={`mt-px size-3.5 shrink-0 ${className}`} />
        <button
          type="button"
          aria-expanded={open}
          onClick={() => setOpen(!open)}
          className="min-w-0 flex-1 text-left"
        >
          <span className="text-fg">{finding.title}</span>
          <span className="ml-2 text-[11px] text-fg-subtle">
            {finding.category.replace("_", " ")} · {finding.basis}
          </span>
        </button>
        <ConfidenceLabel value={finding.confidence} />
        {finding.line !== null && (
          <button
            type="button"
            onClick={() => onReveal(finding.line!)}
            className="shrink-0 font-mono text-[11px] text-accent hover:underline"
            aria-label={`Go to line ${finding.line}`}
          >
            :{finding.line}
          </button>
        )}
      </div>
      {open && (
        <div className="space-y-1 px-8 pb-2 text-xs">
          <p className="whitespace-pre-wrap text-fg">{finding.description}</p>
          <p className="whitespace-pre-wrap text-fg-muted">
            <span className="text-fg-subtle">Reasoning: </span>
            {finding.reasoning}
          </p>
          {finding.suggestion && (
            <p className="whitespace-pre-wrap text-fg-muted">
              <span className="text-fg-subtle">Suggestion: </span>
              {finding.suggestion}
            </p>
          )}
          {typeof finding.metadata.evidence === "string" && finding.metadata.evidence && (
            <pre className="overflow-auto rounded bg-app px-2 py-1 font-mono text-[11px] text-fg-muted">
              {finding.metadata.evidence}
            </pre>
          )}
        </div>
      )}
    </li>
  );
}

/** Module 7: an advisory AI review of the active file, next to the deterministic Problems. */
export function AIReviewPanel() {
  const { state, actions } = useWorkspace();
  const { status, review, runReview } = useAIAssist();
  const [analysisType, setAnalysisType] = useState<AIAnalysisType>("general_review");
  const path = state.activePath;
  const unavailable = unavailableReason(status);
  const shown = review && review.path === path ? review : null;
  const running = shown?.result.state === "loading";

  return (
    <section aria-label="AI review" className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-border px-3 py-1">
        <label htmlFor="ai-review-type" className="text-[11px] text-fg-muted">
          Focus
        </label>
        <select
          id="ai-review-type"
          value={analysisType}
          onChange={(event) => setAnalysisType(event.target.value as AIAnalysisType)}
          className="h-6 rounded border border-border bg-surface-raised px-1.5 text-xs text-fg"
        >
          {AI_ANALYSIS_TYPES.map((type) => (
            <option key={type} value={type}>
              {ANALYSIS_TYPE_LABELS[type]}
            </option>
          ))}
        </select>
        <button
          type="button"
          disabled={!path || running || !!unavailable || status.state === "loading"}
          onClick={() => path && void runReview(path, analysisType)}
          className="rounded bg-accent px-2 py-0.5 text-xs font-medium text-white hover:bg-accent-strong disabled:opacity-50"
        >
          {running ? "Reviewing…" : path ? `Review ${path.split("/").pop()}` : "Review file"}
        </button>
        <span className="text-[11px] text-fg-subtle">
          Uses the current editor content and its problems; nothing is changed.
        </span>
      </div>
      <div className="min-h-0 flex-1 overflow-auto">
        {unavailable && (
          <p role="status" className="px-3 py-2 text-xs text-fg-muted">
            AI unavailable: {unavailable}
          </p>
        )}
        {!path && !unavailable && (
          <p className="px-3 py-2 text-xs text-fg-muted">Open a file to review it with AI.</p>
        )}
        {shown && (
          <div className="space-y-2 py-2">
            <div className="px-3">
              <RemoteStatus
                result={shown.result}
                loading="Reviewing… (this can take up to a minute)"
              >
                {(data) => (
                  <div className="space-y-1">
                    <div className="flex items-center gap-2">
                      <h3 className="text-xs font-semibold text-fg">
                        {ANALYSIS_TYPE_LABELS[data.analysis_type]}
                      </h3>
                      <ConfidenceLabel value={data.confidence} />
                    </div>
                    <p className="text-xs whitespace-pre-wrap text-fg-muted">{data.summary}</p>
                  </div>
                )}
              </RemoteStatus>
            </div>
            {shown.result.state === "ready" && (
              <>
                {shown.result.data.findings.length === 0 ? (
                  <p className="px-3 text-xs text-fg-muted">No findings for this focus.</p>
                ) : (
                  <ul aria-label="AI findings" className="border-y border-border">
                    {shown.result.data.findings.map((finding) => (
                      <FindingItem
                        key={finding.id}
                        finding={finding}
                        onReveal={(line) => void actions.revealPosition(shown.path, line, 1)}
                      />
                    ))}
                  </ul>
                )}
                <div className="px-3">
                  <AdvisoryFooter
                    provider={shown.result.data.provider}
                    model={shown.result.data.model}
                    warnings={shown.result.data.warnings}
                    context={shown.result.data.context}
                  />
                </div>
              </>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
