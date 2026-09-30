"use client";

import { AlertTriangle, CircleX } from "lucide-react";

import type { BackendConnection } from "@/features/backend-status/use-backend-health";
import { useCursor } from "@/features/editor/cursor-context";
import { useAllDiagnostics } from "@/features/problems/problems-panel";
import { isDirty } from "@/features/workspace/state";
import { useWorkspace } from "@/features/workspace/workspace-context";
import { detectLanguage, languageLabel } from "@/lib/languages";

const CONNECTION_VIEW: Record<BackendConnection["state"], { label: string; dot: string }> = {
  checking: { label: "Backend: checking…", dot: "bg-fg-subtle" },
  online: { label: "Backend: online", dot: "bg-success" },
  degraded: { label: "Backend: degraded", dot: "bg-warning" },
  unavailable: { label: "Backend: unavailable", dot: "bg-danger" },
  offline: { label: "Backend: offline", dot: "bg-danger" },
  timeout: { label: "Backend: not responding", dot: "bg-danger" },
  error: { label: "Backend: error", dot: "bg-danger" },
};

function connectionDetail(connection: BackendConnection): string {
  switch (connection.state) {
    case "checking":
      return "Checking the backend health endpoint…";
    case "online":
    case "degraded": {
      const failing = connection.health.checks
        .filter((check) => check.status === "fail")
        .map((check) => check.name);
      return [
        `${connection.health.service} ${connection.health.version} (${connection.health.environment})`,
        `Response time ${connection.latencyMs} ms`,
        failing.length ? `Failing checks: ${failing.join(", ")}` : null,
        `Checked ${connection.checkedAt.toLocaleTimeString()}. Click to re-check.`,
      ]
        .filter(Boolean)
        .join("\n");
    }
    case "unavailable":
      return `The backend is running but a required dependency is failing.\nChecked ${connection.checkedAt.toLocaleTimeString()}. Click to re-check.`;
    default:
      return `${connection.message}\nChecked ${connection.checkedAt.toLocaleTimeString()}. Click to re-check.`;
  }
}

const PERSISTENCE_LABEL = {
  disk: "Saves to disk",
  "browser-memory": "Saves in this tab only",
} as const;

interface StatusBarProps {
  connection: BackendConnection;
  onRecheck(): void;
  onToggleProblems(): void;
}

export function StatusBar({ connection, onRecheck, onToggleProblems }: StatusBarProps) {
  const { state } = useWorkspace();
  const cursor = useCursor();
  const { counts } = useAllDiagnostics();
  const { project, activePath, buffers, editorSettings } = state;
  const buffer = activePath ? buffers[activePath] : undefined;
  const view = CONNECTION_VIEW[connection.state];

  let fileState: string | null = null;
  if (buffer?.status === "ready") {
    if (buffer.saving) fileState = "Saving…";
    else if (buffer.saveError) fileState = "Save failed";
    else fileState = isDirty(buffer) ? "Unsaved" : "Saved";
  }

  const item = "flex h-full items-center gap-1.5 px-2 whitespace-nowrap";
  const interactive = `${item} hover:bg-surface-hover`;

  return (
    <footer
      aria-label="Status bar"
      className="flex h-6 shrink-0 items-center overflow-hidden border-t border-border bg-surface-sunken text-[11px] text-fg-muted"
    >
      <button
        type="button"
        onClick={onRecheck}
        title={connectionDetail(connection)}
        className={interactive}
      >
        <span aria-hidden className={`size-2 rounded-full ${view.dot}`} />
        <span role="status">{view.label}</span>
      </button>
      {project && (
        <button
          type="button"
          onClick={onToggleProblems}
          title="Toggle Problems panel (Ctrl+J)"
          className={interactive}
        >
          <CircleX aria-hidden className="size-3" />
          <span aria-label={`${counts.error} errors`}>{counts.error}</span>
          <AlertTriangle aria-hidden className="size-3" />
          <span aria-label={`${counts.warning} warnings`}>{counts.warning}</span>
        </button>
      )}
      {project && (
        <span className={`${item} hidden md:flex`}>{PERSISTENCE_LABEL[project.persistence]}</span>
      )}

      <span className="flex-1" />

      {buffer?.status === "ready" && activePath && (
        <>
          {cursor && (
            <span className={item}>
              Ln {cursor.line}, Col {cursor.column}
              {cursor.selectedChars > 0 && ` (${cursor.selectedChars} selected)`}
            </span>
          )}
          <span className={`${item} hidden sm:flex`}>Tab Size: {editorSettings.tabSize}</span>
          <span className={`${item} hidden sm:flex`}>UTF-8</span>
          <span className={item}>
            {languageLabel(buffer.languageOverride ?? detectLanguage(activePath))}
          </span>
          {fileState && (
            <span className={`${item} ${fileState === "Save failed" ? "text-danger" : ""}`}>
              {fileState}
            </span>
          )}
        </>
      )}
    </footer>
  );
}
