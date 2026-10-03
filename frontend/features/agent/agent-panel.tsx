"use client";

import {
  AlertTriangle,
  Ban,
  CheckCircle2,
  FileDiff,
  Loader2,
  Search,
  Sparkles,
  Wrench,
  XCircle,
} from "lucide-react";
import { useEffect, useId, useState, type FormEvent, type KeyboardEvent } from "react";

import { useWorkspace } from "@/features/workspace/workspace-context";
import type { AgentAction, AgentEvent, AgentRun } from "@/services/api/agent";

import { useAgent } from "./agent-context";

const SUGGESTIONS = [
  "Explain the problems in this file",
  "Where is this file used in the project?",
  "Fix the problems in this file",
];

/** "line 4" or "lines 4-6"; a selection that ends at column 1 does not include that last line. */
function selectionLabel(sel: { startLine: number; endLine: number; endColumn: number }): string {
  const end = sel.endColumn === 1 && sel.endLine > sel.startLine ? sel.endLine - 1 : sel.endLine;
  return end === sel.startLine ? `line ${end}` : `lines ${sel.startLine}-${end}`;
}

function Elapsed({ startedAt }: { startedAt: number }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  return <>{Math.max(0, Math.round((now - startedAt) / 1000))}s</>;
}

function EventIcon({ event }: { event: AgentEvent }) {
  const cls = "mt-0.5 size-3.5 shrink-0";
  switch (event.type) {
    case "tool_completed":
      return <CheckCircle2 aria-hidden className={`${cls} text-success`} />;
    case "tool_failed":
    case "failed":
      return <XCircle aria-hidden className={`${cls} text-danger`} />;
    case "tool_denied":
      return <Ban aria-hidden className={`${cls} text-warning`} />;
    case "limit_reached":
      return <AlertTriangle aria-hidden className={`${cls} text-warning`} />;
    case "action_proposed":
      return <FileDiff aria-hidden className={`${cls} text-accent`} />;
    case "tool_started":
      return <Search aria-hidden className={`${cls} text-fg-subtle`} />;
    default:
      return <Sparkles aria-hidden className={`${cls} text-fg-subtle`} />;
  }
}

/** What the agent did, as user-facing steps. The model's reasoning is never shown or stored. */
function Activity({ run }: { run: AgentRun }) {
  const shown = run.events.filter((e) => e.type !== "started" && e.type !== "completed");
  return (
    <details className="group" open={run.status !== "completed"}>
      <summary className="cursor-pointer text-[11px] text-fg-muted select-none hover:text-fg">
        Activity · {run.tool_calls.length} tool call{run.tool_calls.length === 1 ? "" : "s"} ·{" "}
        {(run.duration_ms / 1000).toFixed(1)}s
      </summary>
      <ol aria-label="Agent activity" className="mt-1 space-y-0.5 border-l border-border pl-2">
        {shown.map((event, i) => (
          <li key={`${event.at}-${i}`} className="flex gap-1.5 text-[11px] text-fg-muted">
            <EventIcon event={event} />
            <span className="min-w-0">
              {event.tool && <span className="mr-1 font-mono text-fg-subtle">{event.tool}</span>}
              {event.message}
            </span>
          </li>
        ))}
      </ol>
    </details>
  );
}

function ProposedChangeCard({ action }: { action: AgentAction }) {
  const { approve, reject, openReview, decisions, reviewing } = useAgent();
  const { state } = useWorkspace();
  const decision = decisions[action.id];
  const busy = decision?.state === "busy";
  const buffer = state.buffers[action.file_path];
  const dirty = buffer?.status === "ready" && buffer.content !== buffer.savedContent;
  const changed = action.diff
    .split("\n")
    .filter((l) => /^[+-]/.test(l) && !l.startsWith("+++ ") && !l.startsWith("--- ")).length;
  const pending = action.status === "pending";

  return (
    <li
      aria-label={`Proposed change to ${action.file_path}`}
      className="rounded border border-border bg-surface px-2 py-1.5"
    >
      <div className="flex items-start gap-2">
        <Wrench aria-hidden className="mt-0.5 size-3.5 shrink-0 text-accent" />
        <div className="min-w-0 flex-1">
          <p className="text-xs text-fg">{action.summary}</p>
          <p className="truncate font-mono text-[10px] text-fg-subtle" title={action.file_path}>
            {action.file_path} · {changed} changed line{changed === 1 ? "" : "s"} ·{" "}
            <span className={pending ? "text-warning" : "text-fg-muted"}>
              {pending ? "waiting for your review" : action.status}
            </span>
          </p>
        </div>
      </div>
      {pending && (
        <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
          <button
            type="button"
            onClick={() => void openReview(action)}
            aria-pressed={reviewing?.id === action.id}
            className="rounded border border-border px-2 py-0.5 text-[11px] text-fg hover:bg-surface-hover"
          >
            Review diff
          </button>
          <button
            type="button"
            disabled={busy || dirty || state.project?.readOnly}
            onClick={() => void approve(action)}
            className="rounded bg-accent px-2 py-0.5 text-[11px] font-medium text-white hover:bg-accent-strong disabled:opacity-50"
          >
            {busy ? "Working…" : "Apply"}
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => void reject(action)}
            className="rounded border border-border px-2 py-0.5 text-[11px] text-fg hover:bg-surface-hover disabled:opacity-50"
          >
            Reject
          </button>
          {dirty && (
            <span className="text-[10px] text-warning">
              Save or undo your unsaved edits to this file before applying.
            </span>
          )}
        </div>
      )}
      {decision?.state === "error" && (
        <p role="alert" className="mt-1 text-[11px] text-danger">
          {decision.message}
        </p>
      )}
    </li>
  );
}

function RunView({ run }: { run: AgentRun }) {
  return (
    <div className="space-y-2">
      <p className="text-[11px] text-fg-subtle">
        <span className="text-fg-muted">You asked:</span> {run.message}
      </p>
      <Activity run={run} />
      {run.answer && (
        <div className="rounded border border-border bg-surface px-2.5 py-2 text-xs leading-relaxed whitespace-pre-wrap text-fg">
          {run.answer}
        </div>
      )}
      {run.status === "failed" && run.error && (
        <p role="alert" className="text-xs text-danger">
          {run.error.message}
        </p>
      )}
      {run.status === "limit_reached" && !run.answer && (
        <p role="alert" className="text-xs text-warning">
          The agent stopped at a limit before answering. Try a narrower request.
        </p>
      )}
      {run.actions.length > 0 && (
        <ul aria-label="Proposed changes" className="space-y-1.5">
          {run.actions.map((action) => (
            <ProposedChangeCard key={action.id} action={action} />
          ))}
        </ul>
      )}
      {run.warnings.length > 0 && (
        <ul className="space-y-0.5 text-[11px] text-warning">
          {run.warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      )}
      {run.provider && (
        <p className="text-[10px] text-fg-subtle">
          {run.provider} ({run.model}). Answers are advisory; changes are applied only when you
          choose Apply.
        </p>
      )}
    </div>
  );
}

/** The project-aware agent, in the Coding workspace's bottom panel. */
export function AgentPanel() {
  const { status, run, ask, cancel, selection } = useAgent();
  const { state } = useWorkspace();
  const [message, setMessage] = useState("");
  const [includeFile, setIncludeFile] = useState(true);
  const [includeSelection, setIncludeSelection] = useState(true);
  const inputId = useId();
  const unavailable =
    status.state === "error"
      ? status.message
      : status.state === "ready" && !status.data.available
        ? (status.data.detail ?? "The agent is not available.")
        : null;
  const serverProject = Boolean(state.project?.serverProjectId);
  const running = run.state === "running";
  const activePath = state.activePath;
  const problems = activePath
    ? Object.values(state.diagnostics).reduce(
        (n, byFile) => n + (byFile[activePath]?.length ?? 0),
        0,
      )
    : 0;

  const submit = (event?: FormEvent) => {
    event?.preventDefault();
    if (!message.trim() || running || unavailable || !serverProject) return;
    void ask(message, { includeFile, includeSelection });
  };
  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) submit();
  };

  return (
    <div className="flex h-full min-h-0 flex-col md:flex-row">
      <form
        onSubmit={submit}
        aria-label="Ask the agent"
        className="flex min-h-0 shrink-0 flex-col gap-1.5 overflow-y-auto border-b border-border p-2 md:w-[min(26rem,45%)] md:border-r md:border-b-0"
      >
        {!serverProject ? (
          <p className="text-xs text-fg-muted">
            The agent works on projects stored on the server. Open one from the Projects area.
          </p>
        ) : unavailable ? (
          <p role="status" className="text-xs text-fg-muted">
            Agent unavailable: {unavailable}
          </p>
        ) : null}
        <label htmlFor={inputId} className="sr-only">
          Ask about your project
        </label>
        <textarea
          id={inputId}
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          onKeyDown={onKeyDown}
          rows={3}
          maxLength={4000}
          disabled={!serverProject || Boolean(unavailable)}
          placeholder="Ask about this project, the open file, a problem, or request a fix…"
          className="min-h-[3.75rem] w-full flex-1 resize-none rounded border border-border bg-surface px-2 py-1 text-xs text-fg outline-none placeholder:text-fg-subtle focus:border-accent disabled:opacity-60"
        />
        <div className="flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-fg-muted">
          <label className="flex items-center gap-1">
            <input
              type="checkbox"
              checked={includeFile}
              onChange={(e) => setIncludeFile(e.target.checked)}
              className="accent-accent"
            />
            Open file
            {activePath
              ? ` (${activePath.split("/").pop()}, ${problems} problem${problems === 1 ? "" : "s"})`
              : ""}
          </label>
          <label className="flex items-center gap-1">
            <input
              type="checkbox"
              checked={includeSelection}
              disabled={!includeFile || !selection}
              onChange={(e) => setIncludeSelection(e.target.checked)}
              className="accent-accent"
            />
            Selection
            {selection ? ` (${selectionLabel(selection)})` : " (none)"}
          </label>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <button
            type="submit"
            disabled={!message.trim() || running || Boolean(unavailable) || !serverProject}
            className="rounded bg-accent px-2.5 py-1 text-xs font-medium text-white hover:bg-accent-strong disabled:opacity-50"
          >
            Ask agent
          </button>
          {running && (
            <button
              type="button"
              onClick={cancel}
              className="rounded border border-border px-2 py-1 text-xs text-fg hover:bg-surface-hover"
            >
              Cancel
            </button>
          )}
          <span className="text-[10px] text-fg-subtle">Ctrl+Enter</span>
        </div>
        {!running && !unavailable && serverProject && (
          <div className="flex flex-wrap gap-1">
            {SUGGESTIONS.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => setMessage(s)}
                className="rounded-full border border-border px-2 py-0.5 text-[10px] text-fg-muted hover:bg-surface-hover hover:text-fg"
              >
                {s}
              </button>
            ))}
          </div>
        )}
      </form>
      <section
        aria-label="Agent result"
        aria-live="polite"
        className="min-h-0 flex-1 overflow-auto p-2"
      >
        {run.state === "idle" && (
          <p className="text-[11px] leading-relaxed text-fg-subtle">
            The agent reads your project with CodeWalk&apos;s tools (search, semantic retrieval,
            project context, diagnostics, analysis). It never runs your code, and it only proposes
            changes: nothing is applied until you choose Apply.
          </p>
        )}
        {run.state === "running" && (
          <p role="status" className="flex items-center gap-1.5 text-xs text-fg-muted">
            <Loader2 aria-hidden className="size-3.5 animate-spin" />
            Working on “{run.message.slice(0, 80)}”… <Elapsed startedAt={run.startedAt} />
          </p>
        )}
        {run.state === "error" && (
          <p role="alert" className="text-xs text-danger">
            {run.message}
          </p>
        )}
        {run.state === "ready" && <RunView run={run.run} />}
      </section>
    </div>
  );
}
