"use client";

import { X } from "lucide-react";
import type { ReactNode } from "react";

import { IconButton } from "@/components/ui/icon-button";
import { isDirty } from "@/features/workspace/state";
import { useWorkspace } from "@/features/workspace/workspace-context";

import { useAIAssist } from "./ai-assist-context";
import { AdvisoryFooter, ConfidenceLabel, RemoteStatus } from "./ai-common";

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section>
      <h4 className="text-[10px] font-semibold tracking-wider text-fg-subtle uppercase">{title}</h4>
      <div className="mt-0.5 text-xs whitespace-pre-wrap text-fg">{children}</div>
    </section>
  );
}

/** "Explain with AI" result for the selected problem, shown beside the Problems list. */
export function ExplanationPanel() {
  const { explanation, closeExplanation, fix, requestFix, openReview } = useAIAssist();
  const { state, actions } = useWorkspace();
  if (!explanation) return null;
  const { diagnostic, result } = explanation;
  const fixForThis =
    fix?.diagnostic?.id === diagnostic.id && fix.path === diagnostic.file ? fix : null;
  const readOnly = state.project?.readOnly ?? false;

  return (
    <aside
      aria-label="AI explanation"
      className="flex h-full min-h-0 flex-col border-l border-border bg-surface"
    >
      <div className="flex h-8 shrink-0 items-center border-b border-border pr-1 pl-3">
        <h3 className="flex-1 text-[11px] font-semibold tracking-wider text-fg-muted uppercase">
          AI explanation
        </h3>
        <IconButton label="Close explanation" onClick={closeExplanation}>
          <X aria-hidden className="size-3.5" />
        </IconButton>
      </div>
      <div className="min-h-0 flex-1 space-y-3 overflow-auto p-3">
        <Section title="Problem">
          <span className="text-fg">{diagnostic.message}</span>{" "}
          <button
            type="button"
            className="font-mono text-[11px] text-accent-text hover:underline"
            onClick={() =>
              void actions.revealPosition(diagnostic.file, diagnostic.line, diagnostic.column)
            }
          >
            {diagnostic.file}:{diagnostic.line}:{diagnostic.column}
          </button>
        </Section>

        <RemoteStatus
          result={result}
          loading="Explaining… (CodeWalk is gathering related project code and asking the AI provider)"
        >
          {(data) => (
            <div className="space-y-3">
              <div className="flex items-center gap-2">
                <ConfidenceLabel value={data.confidence} />
              </div>
              <Section title="Explanation">{data.explanation}</Section>
              <Section title="Likely cause">{data.cause}</Section>
              <Section title="Impact">{data.impact}</Section>
              <Section title="Suggested fix">{data.suggested_fix}</Section>
              {data.related_code_locations.length > 0 && (
                <Section title="Related code">
                  <ul className="space-y-0.5">
                    {data.related_code_locations.map((location) => (
                      <li key={`${location.file_path}:${location.line}:${location.reason}`}>
                        <button
                          type="button"
                          className="font-mono text-[11px] text-accent-text hover:underline"
                          onClick={() =>
                            location.line
                              ? void actions.revealPosition(location.file_path, location.line, 1)
                              : void actions.openFile(location.file_path)
                          }
                        >
                          {location.file_path}
                          {location.line ? `:${location.line}` : ""}
                        </button>{" "}
                        <span className="text-fg-muted">{location.reason}</span>
                      </li>
                    ))}
                  </ul>
                </Section>
              )}

              <div className="flex flex-wrap items-center gap-2">
                {!fixForThis || fixForThis.result.state === "error" ? (
                  <button
                    type="button"
                    disabled={readOnly}
                    title={readOnly ? "This project is read-only." : undefined}
                    onClick={() => void requestFix(diagnostic)}
                    className="rounded border border-border bg-surface-raised px-2 py-1 text-xs text-fg hover:bg-surface-hover disabled:opacity-50"
                  >
                    Suggest a fix
                  </button>
                ) : null}
                {fixForThis && fixStatus()}
              </div>

              <AdvisoryFooter
                provider={data.provider}
                model={data.model}
                warnings={data.warnings}
                context={data.context}
              />
            </div>
          )}
        </RemoteStatus>
      </div>
    </aside>
  );

  function fixStatus() {
    if (!fixForThis) return null;
    const { result: fixResult, decision } = fixForThis;
    if (fixResult.state === "loading")
      return (
        <span role="status" className="text-xs text-fg-muted">
          Preparing a fix suggestion…
        </span>
      );
    if (fixResult.state === "error")
      return (
        <span role="alert" className="text-xs text-danger">
          {fixResult.message}
        </span>
      );
    if (fixResult.state !== "ready") return null;
    const data = fixResult.data;
    if (data.status === "no_suggestion")
      return (
        <span className="text-xs text-fg-muted">
          No useful fix suggestion. {data.warnings.at(-1) ?? ""}
        </span>
      );
    if (decision === "applied")
      return (
        <span role="status" className="text-xs text-success">
          {isDirty(state.buffers[fixForThis.path])
            ? "Fix applied to the editor (not saved yet). Problems are being re-checked."
            : "Fix applied; the editor now matches the saved file."}
        </span>
      );
    if (decision === "rejected")
      return <span className="text-xs text-fg-muted">Suggestion rejected.</span>;
    return (
      <button
        type="button"
        onClick={openReview}
        className="rounded bg-accent px-2 py-1 text-xs font-medium text-on-accent hover:bg-accent-strong hover:text-on-accent-hover"
      >
        Review suggested fix
      </button>
    );
  }
}
