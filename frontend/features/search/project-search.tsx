"use client";

import { Search } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useWorkspace } from "@/features/workspace/workspace-context";
import { backendLanguageLabel } from "@/lib/format";
import { isApiError } from "@/services/api/errors";
import {
  getIndexStatus,
  getRetrievalStatus,
  indexProject,
  type IndexStatus,
} from "@/services/api/retrieval";
import {
  searchProject,
  SYMBOL_KINDS,
  type SearchResponse,
  type SearchResult,
  type SymbolKind,
} from "@/services/api/search";

const DEBOUNCE_MS = 300;
const LANGUAGES = [
  "python",
  "typescript",
  "typescriptreact",
  "javascript",
  "javascriptreact",
  "markdown",
  "json",
];

type SearchState =
  | { state: "idle" }
  | { state: "loading" }
  | { state: "ready"; data: SearchResponse }
  | { state: "error"; message: string };

function describe(result: SearchResult): string {
  if (result.symbol_name) return `${result.qualified_name ?? result.symbol_name}`;
  if (result.line === null) return result.file_path.split("/").pop() ?? result.file_path;
  return (
    result.snippet?.lines[result.line - result.snippet.start_line]?.trim() || result.match_reason
  );
}

function resultTitle(result: SearchResult): string {
  const parts = [result.match_reason];
  if (result.fusion) {
    if (result.match_type !== "semantic" && result.semantic_similarity != null)
      parts.push(`semantic similarity ${result.semantic_similarity.toFixed(3)}`);
    parts.push(
      `RRF ${result.fusion.rrf_score.toFixed(4)} (deterministic rank ${result.fusion.deterministic_rank ?? "-"}, semantic rank ${result.fusion.semantic_rank ?? "-"})`,
    );
  } else {
    parts.push(`score ${result.score}`);
  }
  return parts.join(" · ");
}

type IndexState =
  | { state: "idle" }
  | { state: "ready"; status: IndexStatus; message?: string }
  | { state: "indexing"; status?: IndexStatus }
  | { state: "error"; message: string; status?: IndexStatus };

/**
 * Semantic retrieval controls, shown only when the server has it enabled and configured:
 * the hybrid toggle and the project's index state with an explicit "Index" action
 * (indexing sends the project's code to the embedding provider, so it never runs implicitly).
 */
function SemanticControls({
  projectId,
  hybrid,
  onHybridChange,
}: {
  projectId: string;
  hybrid: boolean;
  onHybridChange: (value: boolean) => void;
}) {
  const [index, setIndex] = useState<IndexState>({ state: "idle" });

  const refresh = useCallback(
    (signal?: AbortSignal) =>
      getIndexStatus(projectId, undefined, signal)
        .then((status) => setIndex({ state: "ready", status }))
        .catch((error: unknown) => {
          if (isApiError(error) && error.kind === "aborted") return;
          setIndex({
            state: "error",
            message: isApiError(error) ? error.message : "Could not read the index state.",
          });
        }),
    [projectId],
  );

  useEffect(() => {
    const controller = new AbortController();
    void refresh(controller.signal);
    return () => controller.abort();
  }, [refresh]);

  const run = () => {
    const previous = index.state === "idle" ? undefined : index.status;
    setIndex({ state: "indexing", status: previous });
    indexProject(projectId)
      .then((result) =>
        setIndex({
          state: "ready",
          status: result.status,
          message:
            result.remaining_files > 0
              ? `Indexed ${result.files_indexed} file(s); ${result.remaining_files} left - run again to continue.`
              : `Indexed ${result.files_indexed} file(s): ${result.chunks_embedded} chunk(s) embedded, ${result.chunks_reused} reused.`,
        }),
      )
      .catch((error: unknown) =>
        setIndex({
          state: "error",
          status: previous,
          message: isApiError(error) ? error.message : "Indexing failed.",
        }),
      );
  };

  const status = index.state === "idle" ? undefined : index.status;
  const upToDate = status !== undefined && status.stale_files === 0 && status.indexed_files > 0;
  return (
    <div className="space-y-1 text-[11px] text-fg-muted">
      <label className="flex items-center gap-1.5">
        <input
          type="checkbox"
          checked={hybrid}
          onChange={(event) => onHybridChange(event.target.checked)}
          className="accent-accent"
        />
        <span title="Combines deterministic matches with code found by embedding similarity (reciprocal rank fusion).">
          Include semantic matches
        </span>
      </label>
      <div className="flex items-center gap-1.5" aria-live="polite">
        <span className="min-w-0 flex-1 truncate" title={status?.model ?? undefined}>
          {index.state === "indexing"
            ? "Indexing…"
            : status
              ? `Semantic index: ${status.indexed_files}/${status.indexable_files} files${status.stale_files ? ` (${status.stale_files} to update)` : ""}`
              : "Semantic index: …"}
        </span>
        <button
          type="button"
          onClick={run}
          disabled={index.state === "indexing" || upToDate}
          className="shrink-0 rounded border border-border px-1.5 py-0.5 text-[10px] text-fg hover:bg-surface-hover disabled:opacity-50"
          title="Sends new and changed files to the embedding provider. Nothing is executed."
        >
          {status && status.indexed_files > 0 ? "Update index" : "Index project"}
        </button>
      </div>
      {index.state === "ready" && index.message && (
        <p className="text-fg-subtle">{index.message}</p>
      )}
      {index.state === "error" && (
        <p role="alert" className="text-danger">
          {index.message}
        </p>
      )}
    </div>
  );
}

/**
 * Project-aware search over the open server project. Deterministic by default; when the server
 * offers semantic retrieval, results can also include embedding matches (hybrid ranking).
 */
export function ProjectSearch({ focusSignal }: { focusSignal: number }) {
  const { state, actions } = useWorkspace();
  const project = state.project;
  const projectId = project?.serverProjectId;
  const [query, setQuery] = useState("");
  const [language, setLanguage] = useState("");
  const [symbolType, setSymbolType] = useState<SymbolKind | "">("");
  const [result, setResult] = useState<SearchState>({ state: "idle" });
  const [semanticAvailable, setSemanticAvailable] = useState(false);
  const [hybrid, setHybrid] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const activePath = state.activePath;

  useEffect(() => {
    inputRef.current?.focus();
    inputRef.current?.select();
  }, [focusSignal]);

  useEffect(() => {
    if (!projectId) return;
    let active = true;
    getRetrievalStatus()
      .then((status) => {
        if (active) setSemanticAvailable(status.available);
      })
      .catch(() => {
        if (active) setSemanticAvailable(false); // deterministic search keeps working
      });
    return () => {
      active = false;
    };
  }, [projectId]);

  const mode = semanticAvailable && hybrid ? "hybrid" : "deterministic";

  useEffect(() => {
    const text = query.trim();
    if (!projectId || !text) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      setResult({ state: "loading" });
      searchProject(
        projectId,
        {
          query: text,
          language: language || undefined,
          symbolType: symbolType || undefined,
          currentFile: activePath ?? undefined,
          mode,
        },
        undefined,
        controller.signal,
      )
        .then((data) => setResult({ state: "ready", data }))
        .catch((error: unknown) => {
          if (isApiError(error) && error.kind === "aborted") return;
          setResult({
            state: "error",
            message: isApiError(error) ? error.message : "Search failed.",
          });
        });
    }, DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [activePath, language, mode, projectId, query, symbolType]);

  const groups = useMemo(() => {
    if (result.state !== "ready") return [];
    const byFile = new Map<string, SearchResult[]>();
    for (const item of result.data.results) {
      const list = byFile.get(item.file_path) ?? [];
      list.push(item);
      byFile.set(item.file_path, list);
    }
    return [...byFile.entries()];
  }, [result]);

  const open = (item: SearchResult) => {
    if (item.line !== null)
      void actions.revealPosition(item.file_path, item.line, item.column ?? 1);
    else void actions.openFile(item.file_path);
  };

  if (!projectId) {
    return (
      <p className="p-3 text-xs text-fg-muted">
        Project search works on projects stored on the server. Open one from the Projects area.
      </p>
    );
  }

  const select =
    "h-6 min-w-0 flex-1 rounded border border-border bg-surface-raised px-1 text-[11px] text-fg";
  const shownQuery = query.trim();

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="space-y-1.5 border-b border-border p-2">
        <div className="relative">
          <Search
            aria-hidden
            className="pointer-events-none absolute top-1.5 left-2 size-3.5 text-fg-subtle"
          />
          <input
            ref={inputRef}
            type="search"
            aria-label="Search project"
            placeholder="Search project…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            maxLength={200}
            className="w-full rounded border border-border bg-surface px-2 py-1 pl-7 text-xs text-fg outline-none placeholder:text-fg-subtle focus:border-accent"
          />
        </div>
        <div className="flex gap-1.5">
          <select
            aria-label="Language"
            value={language}
            onChange={(e) => setLanguage(e.target.value)}
            className={select}
          >
            <option value="">Any language</option>
            {LANGUAGES.map((id) => (
              <option key={id} value={id}>
                {backendLanguageLabel(id)}
              </option>
            ))}
          </select>
          <select
            aria-label="Symbol type"
            value={symbolType}
            onChange={(e) => setSymbolType(e.target.value as SymbolKind | "")}
            className={select}
          >
            <option value="">Everything</option>
            {SYMBOL_KINDS.map((kind) => (
              <option key={kind} value={kind}>
                {kind.replace("_", " ")}
              </option>
            ))}
          </select>
        </div>
        {semanticAvailable && (
          <SemanticControls projectId={projectId} hybrid={hybrid} onHybridChange={setHybrid} />
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-auto" aria-live="polite">
        {!shownQuery && (
          <p className="p-3 text-[11px] leading-relaxed text-fg-subtle">
            Finds functions, classes, methods, files, imports, identifiers, and text. Results from
            the open file and files related to it by imports rank higher.
            {semanticAvailable &&
              " With semantic matches on, code similar in meaning is included and both lists are merged by rank."}
          </p>
        )}
        {shownQuery && result.state === "loading" && (
          <p role="status" className="p-3 text-xs text-fg-muted">
            Searching…
          </p>
        )}
        {shownQuery && result.state === "error" && (
          <p role="alert" className="p-3 text-xs text-danger">
            {result.message}
          </p>
        )}
        {shownQuery && result.state === "ready" && (
          <>
            <p className="px-3 py-1 text-[11px] text-fg-subtle" title={result.data.ranking}>
              {result.data.total === 0
                ? "No matches."
                : `${result.data.total}${result.data.truncated ? "+" : ""} result${result.data.total === 1 ? "" : "s"} in ${groups.length} file${groups.length === 1 ? "" : "s"}`}
              {result.data.mode_used === "hybrid" && " · hybrid ranking"}
            </p>
            {result.data.warnings.length > 0 && (
              <ul className="px-3 pb-1 text-[11px] text-warning">
                {result.data.warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            )}
            <ul aria-label="Search results">
              {groups.map(([path, items]) => (
                <li key={path} className="pb-1">
                  <p
                    className="truncate px-3 pt-1 font-mono text-[11px] text-fg-muted"
                    title={path}
                  >
                    {path}
                  </p>
                  <ul>
                    {items.map((item) => (
                      <li
                        key={`${item.match_type}:${item.line}:${item.column}:${item.symbol_name}`}
                      >
                        <button
                          type="button"
                          onClick={() => open(item)}
                          title={resultTitle(item)}
                          className="flex w-full items-baseline gap-1.5 py-0.5 pr-2 pl-5 text-left text-xs hover:bg-surface-hover"
                        >
                          <span className="w-14 shrink-0 text-[10px] text-fg-subtle">
                            {item.symbol_type ?? (item.line === null ? "file" : item.match_type)}
                          </span>
                          <span className="min-w-0 flex-1 truncate font-mono text-fg">
                            {describe(item)}
                          </span>
                          {item.match_type === "semantic" && (
                            <span className="shrink-0 rounded border border-border px-1 text-[9px] text-fg-subtle">
                              semantic
                            </span>
                          )}
                          {item.line !== null && (
                            <span className="shrink-0 text-[10px] text-fg-subtle">
                              Line {item.line}
                            </span>
                          )}
                        </button>
                      </li>
                    ))}
                  </ul>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </div>
  );
}
