"use client";

import { Loader2 } from "lucide-react";
import { Fragment, useEffect, useId, useRef, useState, type ReactNode } from "react";

import { buttonClass } from "@/components/ui/page-frame";
import { AiErrorNotice } from "@/features/ai/ai-common";
import type { OpenLocation } from "@/features/insights/insights-panel";
import {
  EXPLAIN_DEPTHS,
  EXPLAIN_TOPICS,
  runAgent,
  type AgentRun,
  type ExplainDepth,
  type ExplainTopic,
} from "@/services/api/agent";
import { isApiError } from "@/services/api/errors";

import { AgentAnswer, useAgentAvailability } from "./project-ask";

/**
 * Project explanation: pick a topic (Overview, Architecture, … Improvement Suggestions) and a depth
 * (Beginner … Deep Dive). The agent's read-only "explain" workflow reads the project's own files
 * (architecture summary, search, semantic retrieval, file contents) and answers with the files it
 * used; it cannot propose changes. Answers are kept per topic and depth for this page visit.
 */

type Result =
  | { state: "loading" }
  | { state: "ready"; data: AgentRun }
  | { state: "error"; message: string; code?: string };

const topicLabel = (id: ExplainTopic) => EXPLAIN_TOPICS.find((t) => t.id === id)?.label ?? id;

export function explainMessage(topic: ExplainTopic, focus: string): string {
  const base = `Explain this project: ${topicLabel(topic)}.`;
  const extra = focus.trim();
  return extra ? `${base} Focus on: ${extra}` : base;
}

export function ProjectExplain({
  projectId,
  onOpen,
  compact = false,
}: {
  projectId: string;
  /** Where a cited file opens; without it, file names are plain text. */
  onOpen?: OpenLocation;
  /** Narrow layout (the Coding sidebar): topics as a select instead of a grid. */
  compact?: boolean;
}) {
  const { checking, unavailable } = useAgentAvailability();
  const [topic, setTopic] = useState<ExplainTopic>("overview");
  const [depth, setDepth] = useState<ExplainDepth>("developer");
  const [focus, setFocus] = useState("");
  const [results, setResults] = useState<Record<string, Result>>({});
  const abort = useRef<AbortController | null>(null);
  const topicId = useId();
  const depthId = useId();
  const focusId = useId();

  useEffect(() => () => abort.current?.abort(), []);
  // Answers belong to one project.
  const [shownProject, setShownProject] = useState(projectId);
  if (shownProject !== projectId) {
    setShownProject(projectId);
    setResults({});
  }

  const key = `${topic}|${depth}|${focus.trim()}`;
  const result = results[key];
  const running = Object.values(results).some((r) => r.state === "loading");

  const explain = async () => {
    if (running || unavailable) return;
    const requestKey = key;
    const controller = new AbortController();
    abort.current = controller;
    setResults((r) => ({ ...r, [requestKey]: { state: "loading" } }));
    try {
      const data = await runAgent(
        {
          projectId,
          message: explainMessage(topic, focus),
          mode: "explain",
          explainTopic: topic,
          explainDepth: depth,
        },
        undefined,
        controller.signal,
      );
      setResults((r) => ({ ...r, [requestKey]: { state: "ready", data } }));
    } catch (e) {
      setResults((r) => {
        const next = { ...r };
        if (controller.signal.aborted) delete next[requestKey];
        else
          next[requestKey] = {
            state: "error",
            message: isApiError(e) ? e.message : "The project could not be explained.",
            code: isApiError(e) ? e.code : undefined,
          };
        return next;
      });
    } finally {
      abort.current = null;
    }
  };

  const disabled = !!unavailable || running;
  const field =
    "rounded border border-border bg-surface-sunken px-2 py-1 text-xs text-fg outline-none focus:border-accent disabled:opacity-60";

  return (
    <div className="space-y-3">
      {checking && (
        <p role="status" className="flex items-center gap-1.5 text-xs text-fg-muted">
          <Loader2 aria-hidden className="size-3.5 animate-spin" /> Checking the agent…
        </p>
      )}
      {unavailable && (
        <p
          role="status"
          className="rounded border border-border bg-surface-sunken px-2 py-1.5 text-xs text-fg-muted"
        >
          Project explanation needs the AI agent: {unavailable}
        </p>
      )}

      {compact ? (
        <div>
          <label htmlFor={topicId} className="block text-[11px] text-fg-muted">
            Topic
          </label>
          <select
            id={topicId}
            value={topic}
            disabled={running}
            onChange={(e) => setTopic(e.target.value as ExplainTopic)}
            className={`${field} w-full`}
          >
            {EXPLAIN_TOPICS.map((t) => (
              <option key={t.id} value={t.id}>
                {t.label}
              </option>
            ))}
          </select>
        </div>
      ) : (
        <div role="group" aria-label="Topic" className="flex flex-wrap gap-1.5">
          {EXPLAIN_TOPICS.map((t) => (
            <button
              key={t.id}
              type="button"
              aria-pressed={topic === t.id}
              disabled={running}
              onClick={() => setTopic(t.id)}
              className={`rounded-full border px-2.5 py-0.5 text-xs disabled:opacity-60 ${
                topic === t.id
                  ? "border-accent bg-accent-muted text-fg"
                  : "border-border text-fg-muted hover:bg-surface-hover hover:text-fg"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      )}

      <div className="flex flex-wrap items-end gap-2">
        <div>
          <label htmlFor={depthId} className="block text-[11px] text-fg-muted">
            Depth
          </label>
          <select
            id={depthId}
            value={depth}
            disabled={running}
            onChange={(e) => setDepth(e.target.value as ExplainDepth)}
            className={field}
          >
            {EXPLAIN_DEPTHS.map((d) => (
              <option key={d.id} value={d.id}>
                {d.label}
              </option>
            ))}
          </select>
        </div>
        <div className="min-w-40 flex-1">
          <label htmlFor={focusId} className="block text-[11px] text-fg-muted">
            Focus (optional)
          </label>
          <input
            id={focusId}
            value={focus}
            maxLength={300}
            disabled={running}
            onChange={(e) => setFocus(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void explain();
            }}
            placeholder="e.g. the checkout flow"
            className={`${field} w-full`}
          />
        </div>
        <button
          type="button"
          disabled={disabled}
          onClick={() => void explain()}
          className={buttonClass.primary}
        >
          {result?.state === "ready" || result?.state === "error" ? "Explain again" : "Explain"}
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
      </div>
      <p className="text-[11px] text-fg-subtle">
        Answers come from this project&apos;s files (the files read are listed). Nothing is changed.
      </p>

      {result?.state === "loading" && (
        <p role="status" className="flex items-center gap-1.5 text-xs text-fg-muted">
          <Loader2 aria-hidden className="size-3.5 animate-spin" /> Reading the project to explain{" "}
          {topicLabel(topic)}…
        </p>
      )}
      {result?.state === "error" && <AiErrorNotice code={result.code} message={result.message} />}
      {result?.state === "ready" && (
        <AgentAnswer
          run={result.data}
          onOpen={onOpen}
          renderAnswer={(text) => <FormattedAnswer text={text} />}
        />
      )}
    </div>
  );
}

// --- A small, safe Markdown subset (headings, lists, code blocks, **bold**, `code`) ---------------

function inline(text: string): ReactNode[] {
  // Split on `code` and **bold**; everything is rendered as text nodes (never as HTML).
  return text.split(/(`[^`]+`|\*\*[^*]+\*\*)/g).map((part, i) => {
    if (part.startsWith("`") && part.endsWith("`") && part.length > 2)
      return (
        <code key={i} className="rounded bg-surface-sunken px-1 font-mono text-[11px]">
          {part.slice(1, -1)}
        </code>
      );
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4)
      return <strong key={i}>{part.slice(2, -2)}</strong>;
    return <Fragment key={i}>{part}</Fragment>;
  });
}

export function FormattedAnswer({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  const lines = text.split(/\r?\n/);
  let list: { ordered: boolean; items: string[] } | null = null;
  const flush = () => {
    if (!list) return;
    const items = list.items.map((item, i) => <li key={i}>{inline(item)}</li>);
    blocks.push(
      list.ordered ? (
        <ol key={blocks.length} className="list-decimal space-y-0.5 pl-5">
          {items}
        </ol>
      ) : (
        <ul key={blocks.length} className="list-disc space-y-0.5 pl-5">
          {items}
        </ul>
      ),
    );
    list = null;
  };
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (line.trimStart().startsWith("```")) {
      flush();
      const code: string[] = [];
      for (i++; i < lines.length && !lines[i].trimStart().startsWith("```"); i++)
        code.push(lines[i]);
      blocks.push(
        <pre
          key={blocks.length}
          className="overflow-x-auto rounded bg-surface-sunken p-2 font-mono text-[11px]"
        >
          {code.join("\n")}
        </pre>,
      );
      continue;
    }
    const heading = /^(#{1,4})\s+(.*)$/.exec(line);
    const bullet = /^\s*[-*]\s+(.*)$/.exec(line);
    const numbered = /^\s*\d+[.)]\s+(.*)$/.exec(line);
    if (heading) {
      flush();
      blocks.push(
        <h4
          key={blocks.length}
          className={`font-semibold text-fg ${heading[1].length <= 2 ? "pt-1 text-[13px]" : ""}`}
        >
          {inline(heading[2])}
        </h4>,
      );
    } else if (bullet || numbered) {
      const ordered = !bullet;
      if (list && list.ordered !== ordered) flush();
      list ??= { ordered, items: [] };
      list.items.push((bullet ?? numbered)![1]);
    } else if (line.trim() === "") {
      flush();
    } else {
      flush();
      blocks.push(<p key={blocks.length}>{inline(line)}</p>);
    }
  }
  flush();
  return <div className="space-y-1.5 text-fg">{blocks}</div>;
}
