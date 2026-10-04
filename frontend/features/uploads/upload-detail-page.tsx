"use client";

import { ArrowLeft, Loader2, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useId, useMemo, useRef, useState, type FormEvent } from "react";

import { buttonClass, PageFrame } from "@/components/ui/page-frame";
import { StateMessage } from "@/components/ui/state-message";
import {
  ArchitectureView,
  ImpactView,
  type OpenLocation,
} from "@/features/insights/insights-panel";
import { LanguageList } from "@/features/projects/projects-page";
import { formatRelativeTime, plural } from "@/lib/format";
import { getAgentStatus, runAgent, type AgentRun, type AgentStatus } from "@/services/api/agent";
import { isApiError } from "@/services/api/errors";
import {
  getArchitecture,
  getImpact,
  type Architecture,
  type Impact,
} from "@/services/api/insights";
import { analyzeProject } from "@/services/api/intelligence";
import {
  getFileContent,
  getProject,
  listFiles,
  type ServerFile,
  type ServerProject,
} from "@/services/api/projects";
import { searchProject, type SearchResult } from "@/services/api/search";

type Remote<T> =
  | { state: "idle" }
  | { state: "loading" }
  | { state: "ready"; data: T }
  | { state: "error"; message: string };

function message(error: unknown, fallback: string): string {
  return isApiError(error) ? error.message : fallback;
}

const TABS = [
  { id: "ask", label: "Ask" },
  { id: "overview", label: "Overview" },
  { id: "impact", label: "Impact" },
  { id: "search", label: "Search" },
  { id: "file", label: "File" },
] as const;
type Tab = (typeof TABS)[number]["id"];

/** Agent workflows that only answer (uploaded projects never receive proposed changes). */
const ASK_MODES = [
  { id: "assist", label: "Ask a question" },
  { id: "review", label: "Review the selected file" },
  { id: "impact", label: "What could break?" },
  { id: "architecture", label: "Explain the architecture" },
] as const;
type AskMode = (typeof ASK_MODES)[number]["id"];

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

function ErrorText({ text }: { text: string }) {
  return (
    <p role="alert" className="text-xs text-danger">
      {text}
    </p>
  );
}

// --- Ask ------------------------------------------------------------------------------------

function AskPanel({
  projectId,
  selectedPath,
  onOpen,
}: {
  projectId: string;
  selectedPath: string | null;
  onOpen: OpenLocation;
}) {
  const [status, setStatus] = useState<Remote<AgentStatus>>({ state: "loading" });
  const [mode, setMode] = useState<AskMode>("assist");
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
      else setRun({ state: "error", message: message(e, "The agent could not answer.") });
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
              onChange={(e) => setMode(e.target.value as AskMode)}
              className={`${input} w-auto`}
            >
              {ASK_MODES.map((m) => (
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
            placeholder="e.g. How does an order total get calculated, and which files are involved?"
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
            The agent reads this upload only and never changes it.
          </span>
        </div>
      </form>

      {running && <Spinner text="The agent is reading the project…" />}
      {run.state === "error" && <ErrorText text={run.message} />}
      {run.state === "ready" && <AgentAnswer run={run.data} onOpen={onOpen} />}
    </div>
  );
}

function AgentAnswer({ run, onOpen }: { run: AgentRun; onOpen: OpenLocation }) {
  const files = run.context.files_inspected;
  return (
    <section aria-label="Agent answer" className="space-y-2 border-t border-border pt-2 text-xs">
      {run.error && <ErrorText text={run.error.message} />}
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
                <button
                  type="button"
                  className="font-mono text-accent hover:underline"
                  onClick={() => onOpen(f.file_path, f.start_line)}
                >
                  {f.file_path}:{f.start_line}
                </button>
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
              <li key={path}>
                <button
                  type="button"
                  className="font-mono text-accent hover:underline"
                  onClick={() => onOpen(path, 1)}
                >
                  {path}
                </button>
              </li>
            ))}
          </ul>
        </div>
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

// --- Overview, impact, search, file ---------------------------------------------------------

function OverviewPanel({ project, analyzing }: { project: ServerProject; analyzing: boolean }) {
  const [architecture, setArchitecture] = useState<Remote<Architecture>>({ state: "idle" });
  const load = useCallback(async () => {
    setArchitecture({ state: "loading" });
    try {
      setArchitecture({ state: "ready", data: await getArchitecture(project.id) });
    } catch (e) {
      setArchitecture({
        state: "error",
        message: message(e, "Could not analyze the architecture."),
      });
    }
  }, [project.id]);
  useEffect(() => {
    if (!analyzing) void Promise.resolve().then(load);
  }, [analyzing, load]);

  return (
    <div className="space-y-3 text-xs">
      <p className="text-fg-muted">
        {plural(project.stats.file_count, "file")} · {plural(project.stats.total_lines, "line")} ·{" "}
        <LanguageList project={project} max={5} />
      </p>
      <section aria-label="Architecture" aria-live="polite" className="space-y-1.5">
        {(analyzing || architecture.state === "loading") && <Spinner text="Analyzing…" />}
        {architecture.state === "error" && <ErrorText text={architecture.message} />}
        {architecture.state === "ready" && <ArchitectureView data={architecture.data} />}
      </section>
    </div>
  );
}

function ImpactPanel({
  projectId,
  selectedPath,
  onOpen,
}: {
  projectId: string;
  selectedPath: string | null;
  onOpen: OpenLocation;
}) {
  const [symbol, setSymbol] = useState("");
  const [impact, setImpact] = useState<Remote<Impact>>({ state: "idle" });
  const symbolId = useId();
  const analyze = async (event: FormEvent) => {
    event.preventDefault();
    if (!selectedPath) return;
    setImpact({ state: "loading" });
    try {
      setImpact({
        state: "ready",
        data: await getImpact(projectId, selectedPath, symbol.trim() || null),
      });
    } catch (e) {
      setImpact({ state: "error", message: message(e, "Could not analyze the impact.") });
    }
  };
  return (
    <section aria-label="Impact analysis" aria-live="polite" className="space-y-2 text-xs">
      <form onSubmit={analyze} className="flex flex-wrap items-end gap-2">
        <p className="font-mono text-fg">{selectedPath ?? "Select a file on the left first."}</p>
        <div>
          <label htmlFor={symbolId} className={label}>
            Symbol (optional)
          </label>
          <input
            id={symbolId}
            value={symbol}
            maxLength={200}
            onChange={(e) => setSymbol(e.target.value)}
            className={`${input} w-40 font-mono`}
          />
        </div>
        <button
          type="submit"
          disabled={!selectedPath || impact.state === "loading"}
          className={buttonClass.secondary}
        >
          Analyze impact
        </button>
      </form>
      {impact.state === "loading" && <Spinner text="Analyzing…" />}
      {impact.state === "error" && <ErrorText text={impact.message} />}
      {impact.state === "ready" && <ImpactView impact={impact.data} onOpen={onOpen} />}
    </section>
  );
}

function SearchPanel({ projectId, onOpen }: { projectId: string; onOpen: OpenLocation }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Remote<SearchResult[]>>({ state: "idle" });
  const queryId = useId();
  const search = async (event: FormEvent) => {
    event.preventDefault();
    if (!query.trim()) return;
    setResults({ state: "loading" });
    try {
      setResults({
        state: "ready",
        data: (await searchProject(projectId, { query: query.trim() })).results,
      });
    } catch (e) {
      setResults({ state: "error", message: message(e, "Search failed.") });
    }
  };
  return (
    <section aria-label="Search" aria-live="polite" className="space-y-2 text-xs">
      <form onSubmit={search} className="flex items-end gap-2">
        <div className="flex-1">
          <label htmlFor={queryId} className={label}>
            Search symbols, files, and text
          </label>
          <input
            id={queryId}
            value={query}
            maxLength={200}
            onChange={(e) => setQuery(e.target.value)}
            className={input}
          />
        </div>
        <button
          type="submit"
          disabled={!query.trim() || results.state === "loading"}
          className={buttonClass.secondary}
        >
          Search
        </button>
      </form>
      {results.state === "loading" && <Spinner text="Searching…" />}
      {results.state === "error" && <ErrorText text={results.message} />}
      {results.state === "ready" && results.data.length === 0 && (
        <p className="text-fg-muted">No matches.</p>
      )}
      {results.state === "ready" && results.data.length > 0 && (
        <ul aria-label="Search results" className="space-y-1">
          {results.data.map((r, i) => (
            <li key={`${r.file_path}:${r.line}:${i}`}>
              <button
                type="button"
                className="font-mono text-accent hover:underline"
                onClick={() => onOpen(r.file_path, r.line ?? 1)}
              >
                {r.file_path}
                {r.line ? `:${r.line}` : ""}
              </button>{" "}
              <span className="text-fg-muted">
                {r.symbol_name ? `${r.symbol_type ?? "symbol"} ${r.symbol_name} · ` : ""}
                {r.match_reason}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function FilePanel({
  projectId,
  file,
  line,
}: {
  projectId: string;
  file: ServerFile | null;
  line: number;
}) {
  const [content, setContent] = useState<Remote<string>>({ state: "idle" });
  const target = useRef<HTMLLIElement>(null);
  useEffect(() => {
    if (!file) return;
    let cancelled = false;
    void Promise.resolve().then(async () => {
      if (cancelled) return;
      setContent({ state: "loading" });
      try {
        const text = await getFileContent(projectId, file.id);
        if (!cancelled) setContent({ state: "ready", data: text ?? "" });
      } catch (e) {
        if (!cancelled)
          setContent({ state: "error", message: message(e, "Could not load the file.") });
      }
    });
    return () => {
      cancelled = true;
    };
  }, [projectId, file]);
  useEffect(() => {
    if (content.state === "ready") target.current?.scrollIntoView({ block: "center" });
  }, [content, line]);

  if (!file) return <p className="text-xs text-fg-muted">Select a file on the left to read it.</p>;
  return (
    <section aria-label={`File ${file.path}`} className="space-y-1 text-xs">
      <p className="font-mono text-fg">
        {file.path}{" "}
        <span className="text-fg-subtle">· read-only · {plural(file.line_count, "line")}</span>
      </p>
      {content.state === "loading" && <Spinner text="Loading…" />}
      {content.state === "error" && <ErrorText text={content.message} />}
      {content.state === "ready" && (
        <ol className="max-h-[60vh] overflow-auto rounded border border-border bg-surface-sunken py-1 font-mono text-[11px] leading-5">
          {content.data.split(/\r?\n/).map((text, i) => (
            <li
              key={i}
              ref={i + 1 === line ? target : undefined}
              className={`grid grid-cols-[3.5rem_1fr] ${i + 1 === line ? "bg-accent/15" : ""}`}
            >
              <span aria-hidden className="pr-2 text-right text-fg-subtle select-none">
                {i + 1}
              </span>
              <span className="pr-2 break-all whitespace-pre-wrap text-fg">{text}</span>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

// --- Page -----------------------------------------------------------------------------------

export function UploadDetailPage({ projectId }: { projectId: string }) {
  const [project, setProject] = useState<Remote<ServerProject>>({ state: "loading" });
  const [files, setFiles] = useState<ServerFile[]>([]);
  const [analyzing, setAnalyzing] = useState(false);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("ask");
  const [selected, setSelected] = useState<string | null>(null);
  const [line, setLine] = useState(1);
  const [filter, setFilter] = useState("");
  const filterId = useId();
  const tabsId = useId();

  const analyze = useCallback(async () => {
    setAnalyzing(true);
    setAnalysisError(null);
    try {
      await analyzeProject(projectId);
      setProject({ state: "ready", data: await getProject(projectId) });
    } catch (e) {
      setAnalysisError(message(e, "The project could not be analyzed."));
    } finally {
      setAnalyzing(false);
    }
  }, [projectId]);

  useEffect(() => {
    let cancelled = false;
    void Promise.resolve().then(async () => {
      try {
        const [data, list] = await Promise.all([getProject(projectId), listFiles(projectId)]);
        if (cancelled) return;
        setProject({ state: "ready", data });
        setFiles(list);
        // A fresh upload has not been analyzed yet: analyze it once, automatically.
        if (data.origin === "upload" && !data.stats.last_analyzed_at && list.length > 0)
          void analyze();
      } catch (e) {
        if (!cancelled)
          setProject({ state: "error", message: message(e, "The upload could not be loaded.") });
      }
    });
    return () => {
      cancelled = true;
    };
  }, [projectId, analyze]);

  const open: OpenLocation = useCallback((path, at) => {
    setSelected(path);
    setLine(at);
    setTab("file");
  }, []);

  const shown = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    return (needle ? files.filter((f) => f.path.toLowerCase().includes(needle)) : files).slice(
      0,
      2000,
    );
  }, [files, filter]);
  const selectedFile = files.find((f) => f.path === selected) ?? null;

  if (project.state === "loading" || project.state === "idle")
    return <StateMessage title="Loading upload…" />;
  if (project.state === "error")
    return (
      <StateMessage
        tone="error"
        title="Unable to open this upload"
        action={
          <Link href="/app/uploads" className={buttonClass.secondary}>
            Back to Uploads
          </Link>
        }
      >
        {project.message}
      </StateMessage>
    );
  const data = project.data;
  if (data.origin !== "upload")
    return (
      <StateMessage
        title="Not an uploaded project"
        action={
          <Link href={`/app/projects/${data.id}`} className={buttonClass.secondary}>
            Open in Projects
          </Link>
        }
      >
        “{data.name}” is a workspace project; it is managed in Projects and Coding.
      </StateMessage>
    );

  return (
    <PageFrame
      title="Uploads"
      meta={data.name}
      actions={
        <>
          <Link href="/app/uploads" className={buttonClass.secondary}>
            <ArrowLeft aria-hidden className="size-3.5" /> All uploads
          </Link>
          <button
            type="button"
            className={buttonClass.secondary}
            disabled={analyzing}
            onClick={() => void analyze()}
          >
            <RefreshCw aria-hidden className="size-3.5" />
            {analyzing ? "Analyzing…" : "Re-analyze"}
          </button>
        </>
      }
    >
      <div className="grid h-full min-h-0 grid-cols-1 md:grid-cols-[16rem_minmax(0,1fr)]">
        <aside
          aria-label="Files"
          className="flex min-h-0 flex-col border-b border-border md:border-r md:border-b-0"
        >
          <div className="space-y-1 border-b border-border p-2">
            <p className="text-[11px] text-fg-muted">
              {plural(files.length, "file")}
              {data.stats.last_analyzed_at &&
                ` · analyzed ${formatRelativeTime(data.stats.last_analyzed_at)}`}
            </p>
            <label htmlFor={filterId} className="sr-only">
              Filter files
            </label>
            <input
              id={filterId}
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder="Filter files"
              className={input}
            />
          </div>
          <ul className="max-h-60 min-h-0 flex-1 overflow-auto py-1 md:max-h-none">
            {shown.map((f) => (
              <li key={f.id}>
                <button
                  type="button"
                  aria-current={f.path === selected ? "true" : undefined}
                  onClick={() => open(f.path, 1)}
                  className={`block w-full truncate px-2 py-0.5 text-left font-mono text-[11px] hover:bg-surface-hover ${
                    f.path === selected ? "bg-surface-hover text-fg" : "text-fg-muted"
                  }`}
                  title={f.path}
                >
                  {f.path}
                </button>
              </li>
            ))}
          </ul>
        </aside>

        <div className="min-h-0 overflow-auto p-3">
          {analysisError && <ErrorText text={analysisError} />}
          <div
            role="tablist"
            aria-label="Analysis"
            className="mb-3 flex gap-1 border-b border-border"
          >
            {TABS.map((t) => (
              <button
                key={t.id}
                type="button"
                role="tab"
                id={`${tabsId}-${t.id}`}
                aria-selected={tab === t.id}
                aria-controls={`${tabsId}-${t.id}-panel`}
                onClick={() => setTab(t.id)}
                className={`-mb-px border-b-2 px-2 py-1 text-xs ${
                  tab === t.id
                    ? "border-accent text-fg"
                    : "border-transparent text-fg-muted hover:text-fg"
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>
          <div role="tabpanel" id={`${tabsId}-${tab}-panel`} aria-labelledby={`${tabsId}-${tab}`}>
            {tab === "ask" && (
              <AskPanel projectId={data.id} selectedPath={selected} onOpen={open} />
            )}
            {tab === "overview" && <OverviewPanel project={data} analyzing={analyzing} />}
            {tab === "impact" && (
              <ImpactPanel projectId={data.id} selectedPath={selected} onOpen={open} />
            )}
            {tab === "search" && <SearchPanel projectId={data.id} onOpen={open} />}
            {tab === "file" && <FilePanel projectId={data.id} file={selectedFile} line={line} />}
          </div>
        </div>
      </div>
    </PageFrame>
  );
}
