"use client";

import type { editor } from "monaco-editor";
import dynamic from "next/dynamic";
import { useEffect, useRef, useState } from "react";

import { StateMessage } from "@/components/ui/state-message";
import { configureMonaco, monacoTheme } from "@/features/editor/monaco-setup";
import { useTheme } from "@/features/theme/theme-context";
import { useWorkspace } from "@/features/workspace/workspace-context";
import { detectLanguage } from "@/lib/languages";

import { useAIAssist } from "./ai-assist-context";
import { ConfidenceLabel } from "./ai-common";

const DiffEditor = dynamic(() => import("@monaco-editor/react").then((m) => m.DiffEditor), {
  ssr: false,
  loading: () => <StateMessage title="Loading diff…" />,
});

/**
 * The read-only Monaco diff. Its two text models are detached from the diff
 * editor before they are disposed: letting @monaco-editor/react dispose them
 * while the editor still holds them throws "TextModel got disposed before
 * DiffEditorWidget model got reset" when the review closes.
 */
export function ReviewDiff({
  path,
  original,
  modified,
}: {
  path: string;
  original: string;
  modified: string;
}) {
  const { theme } = useTheme();
  const diffRef = useRef<editor.IStandaloneDiffEditor | null>(null);
  useEffect(
    () => () => {
      const instance = diffRef.current;
      diffRef.current = null;
      const models = instance?.getModel();
      try {
        instance?.setModel(null);
      } catch {
        // already disposed together with its container
      }
      models?.original.dispose();
      models?.modified.dispose();
    },
    [],
  );
  return (
    <DiffEditor
      original={original}
      modified={modified}
      language={detectLanguage(path)}
      theme={monacoTheme(theme)}
      beforeMount={configureMonaco}
      onMount={(instance) => {
        diffRef.current = instance;
      }}
      originalModelPath={`ai-review:///original/${path}`}
      modifiedModelPath={`ai-review:///suggested/${path}`}
      keepCurrentOriginalModel
      keepCurrentModifiedModel
      options={{
        readOnly: true,
        originalEditable: false,
        renderSideBySide: true,
        automaticLayout: true,
        scrollBeyondLastLine: false,
        minimap: { enabled: false },
      }}
    />
  );
}

/**
 * Side-by-side review of an AI fix for the active file: current code (left)
 * versus suggested code (right). Nothing changes until "Apply fix" is chosen,
 * and only if the file still matches the code the suggestion was made for.
 */
export function FixReview({ path }: { path: string }) {
  const { fix, applyFix, rejectFix, closeReview } = useAIAssist();
  const { state } = useWorkspace();
  const [message, setMessage] = useState<string | null>(null);
  if (!fix || !fix.reviewOpen || fix.path !== path || fix.result.state !== "ready") return null;
  const suggestion = fix.result.data;
  if (suggestion.status !== "suggested") return null;
  const buffer = state.buffers[path];
  const stale = !buffer || buffer.status !== "ready" || buffer.content !== suggestion.original_code;
  const readOnly = state.project?.readOnly ?? false;
  const changed = suggestion.diff
    .split("\n")
    .filter((l) => /^[+-]/.test(l) && !l.startsWith("+++ ") && !l.startsWith("--- ")).length;

  return (
    <div
      role="region"
      aria-label="Review AI fix"
      className="absolute inset-0 z-20 flex min-h-0 flex-col bg-surface"
    >
      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-accent/50 bg-accent-muted/30 px-3 py-1.5">
        <div className="min-w-0 flex-1">
          <p className="truncate text-xs text-fg">
            <span className="font-semibold">Suggested fix</span> · {suggestion.summary}
          </p>
          <p className="truncate text-[11px] text-fg-muted" title={suggestion.explanation}>
            {changed} changed line{changed === 1 ? "" : "s"} · {suggestion.provider} (
            {suggestion.model}) · {suggestion.explanation}
          </p>
        </div>
        <ConfidenceLabel value={suggestion.confidence} />
        <button
          type="button"
          disabled={stale || readOnly}
          onClick={() => {
            if (!applyFix()) setMessage("The file changed after this suggestion was made.");
          }}
          className="rounded bg-accent px-2.5 py-1 text-xs font-medium text-on-accent hover:bg-accent-strong hover:text-on-accent-hover disabled:opacity-50"
        >
          Apply fix
        </button>
        <button
          type="button"
          onClick={rejectFix}
          className="rounded border border-border px-2.5 py-1 text-xs text-fg hover:bg-surface-hover"
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
      {(stale || message || suggestion.warnings.length > 0) && (
        <div
          role={stale ? "alert" : undefined}
          className="shrink-0 border-b border-border px-3 py-1 text-[11px] text-warning"
        >
          {stale
            ? "The file changed after this suggestion was made, so it can no longer be applied. Request a new suggestion."
            : (message ?? suggestion.warnings.join(" "))}
        </div>
      )}
      <div className="grid shrink-0 grid-cols-2 border-b border-border text-[10px] tracking-wider text-fg-subtle uppercase">
        <span className="px-3 py-0.5">Current code</span>
        <span className="px-3 py-0.5">Suggested code</span>
      </div>
      <div className="min-h-0 flex-1" data-testid="fix-diff">
        <ReviewDiff
          path={path}
          original={suggestion.original_code}
          modified={suggestion.suggested_code}
        />
      </div>
    </div>
  );
}
