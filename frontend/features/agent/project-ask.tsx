"use client";

import { Loader2 } from "lucide-react";
import Link from "next/link";
import { useEffect, useId, useRef, useState, type FormEvent } from "react";

import { buttonClass } from "@/components/ui/page-frame";
import { AiErrorNotice } from "@/features/ai/ai-common";
import type { OpenLocation } from "@/features/insights/insights-panel";
import { plural } from "@/lib/format";
import {
  getAgentStatus,
  runAgent,
  type AgentMode,
  type AgentRun,
  type AgentStatus,
} from "@/services/api/agent";
import { isApiError } from "@/services/api/errors";

/**
 * Ask the agent about a project and show only the answer (Projects and Uploads). The agent fetches the
 * context the question needs; nothing is applied from here. Proposed changes (workspace projects only)
 * are reviewed in Coding.
 */

export interface AskModeOption {
  id: AgentMode;
  label: string;
}

type Remote<T> =
  | { state: "idle" }
  | { state: "loading" }
  | { state: "ready"; data: T }
  | { state: "error"; message: string; code?: string };

function message(error: unknown, fallback: string): string {
  return isApiError(error) ? error.message : fallback;
}

const label = "block text-[11px] text-fg-muted";
const input =
  "w-full rounded border border-border bg-surface-sunken px-2 py-1 text-xs text-fg outline-none focus:border-accent";

function Spinner({ text }: { text: string }) {
  return (
    <p role="status" className="flex items-center gap-1.5 text-xs text-fg-muted">
      <Loader2 aria-hidden className="size-3.5 animate-spin" /> {text}
    </p>
  );
}

export function ProjectAsk({
  projectId,
  modes,
  selectedPath = null,
  onOpen,
  readOnly = false,
  placeholder = "e.g. How does authentication work, and which files are involved?",
}: {
  projectId: string;
  /** Workflows offered (the first is the default). */
  modes: readonly AskModeOption[];
  /** A file to focus on, if the page has one selected. */
  selectedPath?: string | null;
  /** Where a cited file opens; without it, file names are plain text. */
  onOpen?: OpenLocation;
  /** The agent never proposes changes here (uploaded projects). */
  readOnly?: boolean;
  placeholder?: string;
}) {
  const [status, setStatus] = useState<Remote<AgentStatus>>({ state: "loading" });
  const [mode, setMode] = useState<AgentMode>(modes[0]?.id ?? "assist");
  const [question, setQuestion] = useState("");
  const [useFile, setUseFile] = useState(true);
  const [run, setRun] = useState<Remote<AgentRun>>({ state: "idle" });
  const abort = useRef<AbortController | null>(null);
  const modeId = useId();
  const questionId = useId();

  useEffect(() => {
    let cancelled = false;
    getAgentStatus()
      .then((data) => !cancelled && setStatus({ state: "ready", data }))
      .catch(
        (e) =>
          !cancelled &&
          setStatus({ state: "error", message: message(e, "Agent status unavailable.") }),
      );
    return () => {
      cancelled = true;
      abort.current?.abort();
    };
  }, []);

  const unavailable =
    status.state === "ready" && !status.data.available
      ? status.data.detail || "The agent is not available."
      : status.state === "error"
        ? status.message
        : null;
  const running = run.state === "loading";

  const ask = async (event: FormEvent) => {
    event.preventDefault();
    if (!question.trim() || running || unavailable) return;
    const controller = new AbortController();
    abort.current = controller;
    setRun({ state: "loading" });
    try {
      const data = await runAgent(
        {
          projectId,
          message: question.trim(),
          mode,
          filePath: useFile && selectedPath ? selectedPath : undefined,
        },
        undefined,
        controller.signal,
      );
      setRun({ state: "ready", data });
    } catch (e) {
      if (controller.signal.aborted) setRun({ state: "idle" });
      else
        setRun({
          state: "error",
          message: message(e, "The agent could not answer."),
          code: isApiError(e) ? e.code : undefined,
        });
    } finally {
      abort.current = null;
    }
  };

  return (
    <div className="space-y-3">
      {status.state === "loading" && <Spinner text="Checking the agent…" />}
      {unavailable && (
        <p
          role="status"
          className="rounded border border-border bg-surface-sunken px-2 py-1.5 text-xs text-fg-muted"
        >
          Agent unavailable: {unavailable} Search, overview, and impact analysis still work.
        </p>
      )}
      <form onSubmit={ask} className="space-y-2">
        <div className="flex flex-wrap items-end gap-2">
          <div>
            <label htmlFor={modeId} className={label}>
              Workflow
            </label>
            <select
              id={modeId}
              value={mode}
              disabled={!!unavailable || running}
              onChange={(e) => setMode(e.target.value as AgentMode)}
              className={`${input} w-auto`}
            >
              {modes.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.label}
                </option>
              ))}
            </select>
          </div>
          <label className="flex items-center gap-1 text-[11px] text-fg-muted">
            <input
              type="checkbox"
              checked={useFile && !!selectedPath}
              disabled={!selectedPath || running}
              onChange={(e) => setUseFile(e.target.checked)}
            />
            Focus on{" "}
            {selectedPath ? <span className="font-mono">{selectedPath}</span> : "a selected file"}
          </label>
        </div>
        <div>
          <label htmlFor={questionId} className={label}>
            Your question
          </label>
          <textarea
            id={questionId}
            rows={3}
            maxLength={4000}
            value={question}
            disabled={!!unavailable || running}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder={placeholder}
            className={`${input} resize-y`}
          />
        </div>
        <div className="flex items-center gap-2">
          <button
            type="submit"
            disabled={!question.trim() || running || !!unavailable}
            className={buttonClass.primary}
          >
            Ask
          </button>
          {running && (
            <button
              type="button"
              className={buttonClass.secondary}
              onClick={() => abort.current?.abort()}
            >
              Cancel
            </button>
          )}
          <span className="text-[11px] text-fg-subtle">
            {readOnly
              ? "The agent reads this upload only and never changes it."
              : "The agent answers what you ask; nothing is changed from here."}
          </span>
        </div>
      </form>

      {running && <Spinner text="The agent is reading the project…" />}
      {run.state === "error" && <AiErrorNotice code={run.code} message={run.message} />}
      {run.state === "ready" && <AgentAnswer run={run.data} onOpen={onOpen} />}
    </div>
  );
}

export function AgentAnswer({ run, onOpen }: { run: AgentRun; onOpen?: OpenLocation }) {
  const files = run.context.files_inspected;
  const pending = run.actions.filter((a) => a.status === "pending");
  const location = (path: string, line: number, text: string) =>
    onOpen ? (
      <button
        type="button"
        className="font-mono text-accent-text hover:underline"
        onClick={() => onOpen(path, line)}
      >
        {text}
      </button>
    ) : (
      <span className="font-mono text-fg">{text}</span>
    );
  return (
    <section aria-label="Agent answer" className="space-y-2 border-t border-border pt-2 text-xs">
      {run.error && <AiErrorNotice code={run.error.code} message={run.error.message} />}
      {run.answer && <div className="whitespace-pre-wrap text-fg">{run.answer}</div>}
      {run.findings.length > 0 && (
        <div>
          <h4 className="font-semibold text-fg-muted">Findings ({run.findings.length})</h4>
          <ul aria-label="Review findings" className="mt-1 space-y-1.5">
            {run.findings.map((f) => (
              <li key={f.id} className="rounded border border-border p-1.5">
                <span className="mr-1 rounded border border-border px-1 text-[10px] uppercase">
                  {f.severity}
                </span>
                <span className="font-medium text-fg">{f.title}</span>{" "}
                {location(f.file_path, f.start_line, `${f.file_path}:${f.start_line}`)}
                <p className="mt-0.5 text-fg-muted">{f.explanation}</p>
                {f.suggestion && <p className="mt-0.5 text-fg-muted">Suggestion: {f.suggestion}</p>}
              </li>
            ))}
          </ul>
        </div>
      )}
      {files.length > 0 && (
        <div>
          <h4 className="font-semibold text-fg-muted">Files read ({files.length})</h4>
          <ul aria-label="Files inspected" className="mt-0.5 flex flex-wrap gap-x-3 gap-y-0.5">
            {files.map((path) => (
              <li key={path}>{location(path, 1, path)}</li>
            ))}
          </ul>
        </div>
      )}
      {pending.length > 0 && (
        <p role="status" className="rounded border border-border bg-surface-sunken px-2 py-1.5">
          {plural(pending.length, "proposed change")} waiting for your review. Nothing was applied.{" "}
          <Link
            href={`/app/coding?project=${encodeURIComponent(run.project_id)}`}
            className="text-accent-text hover:underline"
          >
            Review in Coding
          </Link>
        </p>
      )}
      {run.warnings.length > 0 && (
        <ul className="list-disc pl-4 text-warning">
          {run.warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      )}
      <p className="text-[10px] text-fg-subtle">
        {run.model ? `${run.provider ?? "AI"} · ${run.model} · ` : ""}
        {plural(run.tool_calls.length, "tool call")} · {(run.duration_ms / 1000).toFixed(1)} s
      </p>
    </section>
  );
}
