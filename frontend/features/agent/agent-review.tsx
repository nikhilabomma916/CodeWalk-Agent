"use client";

import { useMemo } from "react";

import { ReviewDiff } from "@/features/ai/fix-review";
import { useWorkspace } from "@/features/workspace/workspace-context";
import { applyProposedChanges } from "@/services/api/agent";

import { useAgent } from "./agent-context";

/**
 * Side-by-side review of an agent proposal for the active file: the saved file (left) versus the
 * file with the proposal applied (right). Apply is offered only while the proposal still matches the
 * saved file and there are no unsaved edits; the backend re-checks both before writing anything.
 */
export function AgentReview({ path }: { path: string }) {
  const { reviewing, approve, reject, closeReview, decisions } = useAgent();
  const { state } = useWorkspace();
  const buffer = state.buffers[path];
  const action = reviewing?.file_path === path ? reviewing : null;
  const suggested = useMemo(
    () =>
      action && buffer?.status === "ready"
        ? applyProposedChanges(buffer.savedContent, action.changes)
        : null,
    [action, buffer],
  );
  if (!action || !buffer || buffer.status !== "ready") return null;
  const stale = suggested === null;
  const dirty = buffer.content !== buffer.savedContent;
  const busy = decisions[action.id]?.state === "busy";
  const error = decisions[action.id]?.state === "error" ? decisions[action.id]?.message : null;

  return (
    <div
      role="region"
      aria-label="Review proposed change"
      className="absolute inset-0 z-20 flex min-h-0 flex-col bg-surface"
    >
      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-accent/50 bg-accent-muted/30 px-3 py-1.5">
        <div className="min-w-0 flex-1">
          <p className="truncate text-xs text-fg">
            <span className="font-semibold">Agent proposal</span> · {action.summary}
          </p>
          <p className="truncate text-[11px] text-fg-muted" title={action.explanation}>
            {action.explanation}
          </p>
        </div>
        <button
          type="button"
          disabled={stale || dirty || busy || state.project?.readOnly}
          onClick={() => void approve(action)}
          className="rounded bg-accent px-2.5 py-1 text-xs font-medium text-white hover:bg-accent-strong disabled:opacity-50"
        >
          {busy ? "Applying…" : "Apply"}
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => void reject(action)}
          className="rounded border border-border px-2.5 py-1 text-xs text-fg hover:bg-surface-hover disabled:opacity-50"
        >
          Reject
        </button>
        <button
          type="button"
          onClick={closeReview}
          className="rounded px-2 py-1 text-xs text-fg-muted hover:bg-surface-hover hover:text-fg"
        >
          Close review
        </button>
      </div>
      {(stale || dirty || error) && (
        <div
          role="alert"
          className="shrink-0 border-b border-border px-3 py-1 text-[11px] text-warning"
        >
          {stale
            ? "The file changed after this proposal was made, so it can no longer be applied. Ask the agent again."
            : dirty
              ? "This file has unsaved edits. Save or undo them before applying the proposal."
              : error}
        </div>
      )}
      <div className="grid shrink-0 grid-cols-2 border-b border-border text-[10px] tracking-wider text-fg-subtle uppercase">
        <span className="px-3 py-0.5">Saved file</span>
        <span className="px-3 py-0.5">With the proposed change</span>
      </div>
      <div className="min-h-0 flex-1" data-testid="agent-diff">
        <ReviewDiff
          path={`agent/${action.id}/${path}`}
          original={buffer.savedContent}
          modified={suggested ?? buffer.savedContent}
        />
      </div>
    </div>
  );
}
