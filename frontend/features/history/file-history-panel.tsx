"use client";

import { Loader2, RotateCcw, Sparkles, Undo2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { useConfirm } from "@/components/ui/confirm-dialog";
import { ReviewDiff } from "@/features/ai/fix-review";
import { useWorkspace } from "@/features/workspace/workspace-context";
import { formatDateTime, formatRelativeTime } from "@/lib/format";
import { listAgentActions, undoAgentAction, type AgentAction } from "@/services/api/agent";
import { isApiError } from "@/services/api/errors";
import {
  getFileVersion,
  listFileVersions,
  restoreFileVersion,
  type FileVersionSummary,
} from "@/services/api/projects";

const SOURCE_LABEL: Record<string, string> = {
  create: "Created",
  edit: "Edited",
  restore: "Restored",
  scan: "Rescanned",
};

const STATUS_LABEL: Record<string, string> = {
  pending: "waiting for review",
  applied: "applied",
  rejected: "rejected",
  stale: "not applied (file changed)",
};

type Load<T> =
  { state: "loading" } | { state: "ready"; data: T } | { state: "error"; message: string };

const message = (error: unknown, fallback: string) =>
  isApiError(error) ? error.message : fallback;

/** The DiffBlock style of the agent panel, for an AI change's unified diff. */
function UnifiedDiff({ diff }: { diff: string }) {
  return (
    <pre className="mt-1 max-h-64 overflow-auto rounded border border-border bg-surface-sunken p-1.5 font-mono text-[10px] leading-snug">
      {diff.split("\n").map((line, i) => (
        <span
          key={i}
          className={
            line.startsWith("+") && !line.startsWith("+++")
              ? "block text-success"
              : line.startsWith("-") && !line.startsWith("---")
                ? "block text-danger"
                : "block text-fg-muted"
          }
        >
          {line || " "}
        </span>
      ))}
    </pre>
  );
}

/** Versions of the open file: view, compare with the editor, restore. */
function FileVersions({
  projectId,
  path,
  fileId,
  aiVersions,
}: {
  projectId: string;
  path: string;
  fileId: string;
  aiVersions: Map<number, AgentAction>;
}) {
  const { state, actions } = useWorkspace();
  const confirm = useConfirm();
  const [versions, setVersions] = useState<Load<FileVersionSummary[]>>({ state: "loading" });
  const [compare, setCompare] = useState<{ version: number; content: string } | null>(null);
  const [busy, setBusy] = useState<number | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const buffer = state.buffers[path];
  const savedContent = buffer?.status === "ready" ? buffer.savedContent : undefined;

  const load = useCallback(async () => {
    try {
      setVersions({ state: "ready", data: await listFileVersions(projectId, fileId) });
    } catch (error) {
      setVersions({ state: "error", message: message(error, "Unable to load the file history.") });
    }
  }, [fileId, projectId]);

  // Reload when the saved content changes (a save, a restore, an applied AI change).
  useEffect(() => {
    let cancelled = false;
    void Promise.resolve().then(() => {
      if (!cancelled) void load();
    });
    return () => {
      cancelled = true;
    };
  }, [load, savedContent]);

  const show = async (version: number) => {
    setBusy(version);
    setNotice(null);
    try {
      const data = await getFileVersion(projectId, fileId, version);
      setCompare({ version, content: data.content });
    } catch (error) {
      setNotice(message(error, "Unable to load this version."));
    } finally {
      setBusy(null);
    }
  };

  const restore = async (version: number) => {
    const unsaved = buffer?.status === "ready" && buffer.content !== buffer.savedContent;
    const choice = await confirm({
      title: `Restore version ${version} of ${path}?`,
      message:
        "The current content stays in the history as an earlier version; the restore is saved as a new version." +
        (unsaved ? " Your unsaved edits in the editor will be replaced." : ""),
      actions: [
        { value: "cancel", label: "Cancel" },
        { value: "restore", label: "Restore" },
      ],
      cancelValue: "cancel",
    });
    if (choice !== "restore") return;
    setBusy(version);
    setNotice(null);
    try {
      const saved = await restoreFileVersion(projectId, fileId, version);
      actions.syncSavedContent(saved.path, saved.content);
      setCompare(null);
      setNotice(`Restored version ${version}.`);
      await load();
    } catch (error) {
      setNotice(message(error, "The version could not be restored."));
    } finally {
      setBusy(null);
    }
  };

  if (versions.state === "loading")
    return <p className="text-[11px] text-fg-muted">Loading history…</p>;
  if (versions.state === "error")
    return (
      <p role="alert" className="text-[11px] text-danger">
        {versions.message}
      </p>
    );
  const latest = versions.data[0]?.version;
  return (
    <div className="space-y-2">
      {notice && (
        <p role="status" className="text-[11px] text-fg-muted">
          {notice}
        </p>
      )}
      <ol aria-label={`Versions of ${path}`} className="space-y-1">
        {versions.data.map((v) => {
          const ai = aiVersions.get(v.version);
          return (
            <li
              key={v.version}
              className="rounded border border-border bg-surface px-2 py-1.5 text-[11px]"
            >
              <div className="flex items-center gap-1.5">
                <span className="font-mono text-fg">v{v.version}</span>
                <span className="text-fg-muted">
                  {ai ? "AI change" : (SOURCE_LABEL[v.source] ?? v.source)}
                </span>
                {v.version === latest && (
                  <span className="rounded bg-accent-muted px-1 text-[10px] text-fg">current</span>
                )}
                <span className="flex-1" />
                <time
                  className="text-fg-subtle"
                  dateTime={v.created_at}
                  title={formatDateTime(v.created_at)}
                >
                  {formatRelativeTime(v.created_at)}
                </time>
              </div>
              {ai && (
                <p className="mt-0.5 flex items-start gap-1 text-fg-muted">
                  <Sparkles aria-hidden className="mt-0.5 size-3 shrink-0 text-accent-text" />
                  {ai.summary}
                </p>
              )}
              <div className="mt-1 flex gap-1.5">
                <button
                  type="button"
                  disabled={busy !== null}
                  onClick={() => void show(v.version)}
                  className="rounded border border-border px-1.5 py-0.5 text-[10px] text-fg hover:bg-surface-hover disabled:opacity-50"
                >
                  Compare with editor
                </button>
                {v.version !== latest && (
                  <button
                    type="button"
                    disabled={busy !== null}
                    onClick={() => void restore(v.version)}
                    className="flex items-center gap-1 rounded border border-border px-1.5 py-0.5 text-[10px] text-fg hover:bg-surface-hover disabled:opacity-50"
                  >
                    {busy === v.version ? (
                      <Loader2 aria-hidden className="size-3 animate-spin" />
                    ) : (
                      <RotateCcw aria-hidden className="size-3" />
                    )}
                    Restore
                  </button>
                )}
              </div>
            </li>
          );
        })}
      </ol>
      {compare && buffer?.status === "ready" && (
        <section
          aria-label={`Version ${compare.version} compared with the editor`}
          className="space-y-1"
        >
          <div className="flex items-center gap-2 text-[11px] text-fg-muted">
            <span className="flex-1">v{compare.version} (left) and the editor (right)</span>
            <button type="button" className="underline" onClick={() => setCompare(null)}>
              Close
            </button>
          </div>
          <div className="h-72 overflow-hidden rounded border border-border">
            <ReviewDiff path={path} original={compare.content} modified={buffer.content} />
          </div>
        </section>
      )}
    </div>
  );
}

/** AI changes of the project: what, why, which file, the diff, and Undo. */
function AiChanges({
  projectId,
  items,
  reload,
}: {
  projectId: string;
  items: AgentAction[];
  reload(): Promise<void>;
}) {
  const { actions } = useWorkspace();
  const confirm = useConfirm();
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const undo = async (action: AgentAction) => {
    const created = action.result.created === true;
    const choice = await confirm({
      title: `Undo “${action.summary}”?`,
      message: created
        ? `${action.file_path} was created by this AI change and will be deleted.`
        : `${action.file_path} goes back to its content before this AI change (saved as a new version).`,
      actions: [
        { value: "cancel", label: "Cancel" },
        { value: "undo", label: "Undo", variant: created ? "danger" : undefined },
      ],
      cancelValue: "cancel",
    });
    if (choice !== "undo") return;
    setBusy(action.id);
    setNotice(null);
    try {
      const result = await undoAgentAction(action.id);
      if (result.file) actions.syncSavedContent(result.file.path, result.file.content);
      if (result.deleted) await actions.refreshEntries();
      setNotice(`Undid “${action.summary}”.`);
      await reload();
    } catch (error) {
      setNotice(message(error, "The AI change could not be undone."));
    } finally {
      setBusy(null);
    }
  };

  if (items.length === 0)
    return (
      <p className="text-[11px] text-fg-subtle">
        No AI changes yet. Changes the agent proposes appear here with their reason and diff.
      </p>
    );
  return (
    <div className="space-y-1.5">
      {notice && (
        <p role="status" className="text-[11px] text-fg-muted">
          {notice}
        </p>
      )}
      <ul aria-label={`AI changes in this project (${projectId})`} className="space-y-1">
        {items.map((action) => {
          const undone = action.result.undone === true;
          return (
            <li
              key={action.id}
              className="rounded border border-border bg-surface px-2 py-1.5 text-[11px]"
            >
              <div className="flex items-start gap-1.5">
                <Sparkles aria-hidden className="mt-0.5 size-3 shrink-0 text-accent-text" />
                <div className="min-w-0 flex-1">
                  <p className="text-fg">{action.summary}</p>
                  <p className="text-fg-muted">
                    <button
                      type="button"
                      className="font-mono underline-offset-2 hover:underline"
                      onClick={() => void actions.openFile(action.file_path)}
                    >
                      {action.file_path}
                    </button>{" "}
                    · {undone ? "undone" : (STATUS_LABEL[action.status] ?? action.status)}
                    {action.kind === "create_file" ? " · new file" : ""} ·{" "}
                    <time dateTime={action.created_at} title={formatDateTime(action.created_at)}>
                      {formatRelativeTime(action.created_at)}
                    </time>
                  </p>
                </div>
                {action.status === "applied" && !undone && (
                  <button
                    type="button"
                    disabled={busy !== null}
                    onClick={() => void undo(action)}
                    className="flex shrink-0 items-center gap-1 rounded border border-border px-1.5 py-0.5 text-[10px] text-fg hover:bg-surface-hover disabled:opacity-50"
                  >
                    {busy === action.id ? (
                      <Loader2 aria-hidden className="size-3 animate-spin" />
                    ) : (
                      <Undo2 aria-hidden className="size-3" />
                    )}
                    Undo
                  </button>
                )}
              </div>
              <details className="mt-1">
                <summary className="cursor-pointer text-fg-muted hover:text-fg">
                  Why and diff
                </summary>
                <p className="mt-1 whitespace-pre-wrap text-fg-muted">{action.explanation}</p>
                <UnifiedDiff diff={action.diff} />
              </details>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/** Right-sidebar History: the open file's versions and the project's AI changes. */
export function FileHistoryPanel() {
  const { state, actions } = useWorkspace();
  const projectId = state.project?.serverProjectId;
  const path = state.activePath;
  const fileId = path ? actions.serverFileId(path) : null;
  const [aiChanges, setAiChanges] = useState<Load<AgentAction[]>>({ state: "loading" });

  const loadAi = useCallback(async () => {
    if (!projectId) return;
    try {
      setAiChanges({ state: "ready", data: (await listAgentActions(projectId)).items });
    } catch (error) {
      setAiChanges({ state: "error", message: message(error, "Unable to load the AI changes.") });
    }
  }, [projectId]);

  useEffect(() => {
    let cancelled = false;
    void Promise.resolve().then(() => {
      if (!cancelled) void loadAi();
    });
    return () => {
      cancelled = true;
    };
  }, [loadAi]);

  if (!projectId)
    return (
      <p className="p-3 text-xs text-fg-muted">
        History is kept for projects stored by CodeWalk. Save this project to CodeWalk (Agent tab)
        to keep versions of every file.
      </p>
    );

  // Versions written by an applied AI change, by version number (for the open file).
  const aiVersions = new Map<number, AgentAction>();
  if (aiChanges.state === "ready")
    for (const a of aiChanges.data)
      if (a.status === "applied" && a.file_path === path && typeof a.result.version === "number")
        aiVersions.set(a.result.version, a);

  return (
    <div className="h-full space-y-4 overflow-auto p-2">
      <section aria-labelledby="history-file" className="space-y-1.5">
        <h3
          id="history-file"
          className="text-[11px] font-semibold tracking-wider text-fg-muted uppercase"
        >
          This file{path ? `: ${path.split("/").pop()}` : ""}
        </h3>
        {!path ? (
          <p className="text-[11px] text-fg-subtle">Open a file to see its versions.</p>
        ) : !fileId ? (
          <p className="text-[11px] text-fg-subtle">Save the file to start its history.</p>
        ) : (
          <FileVersions projectId={projectId} path={path} fileId={fileId} aiVersions={aiVersions} />
        )}
      </section>
      <section aria-labelledby="history-ai" className="space-y-1.5">
        <h3
          id="history-ai"
          className="text-[11px] font-semibold tracking-wider text-fg-muted uppercase"
        >
          AI changes
        </h3>
        {aiChanges.state === "loading" ? (
          <p className="text-[11px] text-fg-muted">Loading AI changes…</p>
        ) : aiChanges.state === "error" ? (
          <p role="alert" className="text-[11px] text-danger">
            {aiChanges.message}
          </p>
        ) : (
          <AiChanges projectId={projectId} items={aiChanges.data} reload={loadAi} />
        )}
      </section>
    </div>
  );
}
