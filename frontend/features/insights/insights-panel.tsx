"use client";

import { Loader2, Trash2 } from "lucide-react";
import { useCallback, useEffect, useId, useRef, useState, type FormEvent } from "react";

import { useWorkspace } from "@/features/workspace/workspace-context";
import { isApiError } from "@/services/api/errors";
import {
  MEMORY_KINDS,
  addMemory,
  deleteMemory,
  getArchitecture,
  getImpact,
  listMemory,
  type Architecture,
  type Impact,
  type InsightLocation,
  type MemoryItem,
  type MemoryKind,
} from "@/services/api/insights";

type Remote<T> =
  | { state: "idle" }
  | { state: "loading" }
  | { state: "ready"; data: T }
  | { state: "error"; message: string };

function message(error: unknown, fallback: string): string {
  return isApiError(error) ? error.message : fallback;
}

/** Where a clicked location goes: the Coding editor by default, or a caller-provided view. */
export type OpenLocation = (path: string, line: number) => void;

function Locations({
  title,
  items,
  onOpen,
}: {
  title: string;
  items: InsightLocation[];
  onOpen?: OpenLocation;
}) {
  const { actions } = useWorkspace();
  if (items.length === 0) return null;
  const open: OpenLocation = onOpen ?? ((path, line) => void actions.revealPosition(path, line, 1));
  return (
    <div>
      <h4 className="text-[11px] font-semibold text-fg-muted">
        {title} ({items.length})
      </h4>
      <ul className="mt-0.5 space-y-0.5">
        {items.map((item) => (
          <li key={item.file_path} className="text-[11px] text-fg">
            <span
              className={`mr-1 rounded border px-1 text-[10px] uppercase ${
                item.relationship === "confirmed"
                  ? "border-success text-success"
                  : "border-warning text-warning"
              }`}
            >
              {item.relationship}
            </span>
            <button
              type="button"
              onClick={() => open(item.file_path, item.lines[0] ?? 1)}
              className="font-mono text-accent hover:underline"
            >
              {item.file_path}
              {item.lines.length ? `:${item.lines.join(",")}` : ""}
            </button>
            <span className="ml-1 text-fg-subtle">
              {item.evidence}
              {item.chain.length > 2 ? ` (via ${item.chain.slice(1, -1).join(" → ")})` : ""}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function ImpactView({ impact, onOpen }: { impact: Impact; onOpen?: OpenLocation }) {
  // A symbol the file does not define has no dependents of its own: say so instead of "nothing
  // depends on it", which would imply the symbol exists.
  const undefinedSymbol = impact.symbol !== null && impact.definitions.length === 0;
  return (
    <div className="space-y-1.5">
      {undefinedSymbol && (
        <p className="text-[11px] text-fg-muted">This symbol is not defined in the current file.</p>
      )}
      {impact.definitions.length > 0 && (
        <p className="text-[11px] text-fg-muted">
          Defined at line {impact.definitions.map((d) => d.lines[0]).join(", ")}
          {impact.same_file_references.length > 0 &&
            `; used in the same file on line ${impact.same_file_references.join(", ")}`}
          .
        </p>
      )}
      <Locations title="Direct dependents" items={impact.direct_dependents} onOpen={onOpen} />
      <Locations title="Indirect dependents" items={impact.indirect_dependents} onOpen={onOpen} />
      <Locations title="Related tests" items={impact.related_tests} onOpen={onOpen} />
      {impact.related_api_routes.length > 0 && (
        <div>
          <h4 className="text-[11px] font-semibold text-fg-muted">HTTP routes</h4>
          <ul className="font-mono text-[11px] text-fg">
            {impact.related_api_routes.map((r) => (
              <li key={`${r.file_path}:${r.line}`}>
                {r.method} {r.path}{" "}
                <span className="text-fg-subtle">
                  ({r.file_path}:{r.line})
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
      <Locations
        title="Possible references (same name, no import)"
        items={impact.possible_references}
        onOpen={onOpen}
      />
      {!undefinedSymbol &&
        impact.direct_dependents.length +
          impact.indirect_dependents.length +
          impact.possible_references.length ===
          0 && <p className="text-[11px] text-fg-muted">No other project file depends on it.</p>}
      <p className="text-[10px] text-fg-subtle">{impact.limitations.join(" ")}</p>
    </div>
  );
}

export function ArchitectureView({ data }: { data: Architecture }) {
  return (
    <div className="space-y-1.5 text-[11px]">
      <p className="text-fg-muted">
        {data.files} files ·{" "}
        {Object.entries(data.languages)
          .map(([l, n]) => `${n} ${l}`)
          .join(", ")}{" "}
        · {data.tests} test file{data.tests === 1 ? "" : "s"}
      </p>
      <table className="w-full text-left">
        <caption className="sr-only">Components</caption>
        <thead>
          <tr className="text-fg-subtle">
            <th className="font-normal">Component</th>
            <th className="font-normal">Files</th>
            <th className="font-normal">Roles</th>
          </tr>
        </thead>
        <tbody>
          {data.components.slice(0, 12).map((c) => (
            <tr key={c.name} className="align-top text-fg">
              <td className="pr-2 font-mono">{c.name}</td>
              <td className="pr-2">{c.files}</td>
              <td className="text-fg-muted">
                {Object.entries(c.roles)
                  .map(([r, n]) => `${n} ${r.replace("_", " ")}`)
                  .join(", ")}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {data.links.length > 0 && (
        <div>
          <h4 className="font-semibold text-fg-muted">Imports between components</h4>
          <ul className="font-mono text-fg">
            {data.links.slice(0, 12).map((l) => (
              <li key={`${l.source}->${l.target}`}>
                {l.source} → {l.target} <span className="text-fg-subtle">({l.imports})</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {data.api_routes.length > 0 && (
        <div>
          <h4 className="font-semibold text-fg-muted">HTTP routes ({data.api_routes.length})</h4>
          <ul className="font-mono text-fg">
            {data.api_routes.slice(0, 15).map((r) => (
              <li key={`${r.file_path}:${r.line}`}>
                {r.method} {r.path}
              </li>
            ))}
          </ul>
        </div>
      )}
      {data.entry_points.length > 0 && (
        <p className="text-fg-muted">Entry points: {data.entry_points.join(", ")}</p>
      )}
      <p className="text-[10px] text-fg-subtle">{data.limitations.join(" ")}</p>
    </div>
  );
}

function ProjectNotes({ projectId }: { projectId: string }) {
  const [items, setItems] = useState<Remote<{ items: MemoryItem[]; limit: number }>>({
    state: "loading",
  });
  const [kind, setKind] = useState<MemoryKind>("convention");
  const [text, setText] = useState("");
  const [error, setError] = useState<{ action: "save" | "delete"; message: string } | null>(null);
  const kindId = useId();
  const textId = useId();
  const textInput = useRef<HTMLInputElement>(null);
  const deleteButtons = useRef(new Map<string, HTMLButtonElement>());
  // Where focus goes once the list re-renders after a delete: a note id (its delete button) or the
  // note input. Without this, focus falls back to the page body when the focused button unmounts.
  const focusAfterDelete = useRef<{ noteId: string | null } | null>(null);

  const load = useCallback(async () => {
    try {
      setItems({ state: "ready", data: await listMemory(projectId) });
    } catch (e) {
      setItems({ state: "error", message: message(e, "Could not load project notes.") });
    }
  }, [projectId]);
  useEffect(() => {
    void Promise.resolve().then(load);
  }, [load]);
  useEffect(() => {
    const target = focusAfterDelete.current;
    if (!target || items.state === "loading") return;
    focusAfterDelete.current = null;
    const button = target.noteId ? deleteButtons.current.get(target.noteId) : undefined;
    (button ?? textInput.current)?.focus();
  }, [items]);

  const onTextChange = (value: string) => {
    setText(value);
    // The credential warning is about text that is no longer there; the next save re-validates.
    if (!value.trim() && error?.action === "save") setError(null);
  };
  const add = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    try {
      await addMemory(projectId, kind, text);
      setText("");
      await load();
    } catch (e) {
      setError({ action: "save", message: message(e, "Could not save the note.") });
    }
  };
  const remove = async (id: string) => {
    setError(null);
    const notes = items.state === "ready" ? items.data.items : [];
    const index = notes.findIndex((item) => item.id === id);
    const neighbour = notes[index + 1] ?? notes[index - 1];
    try {
      await deleteMemory(projectId, id);
      focusAfterDelete.current = { noteId: neighbour?.id ?? null };
      await load();
    } catch (e) {
      setError({ action: "delete", message: message(e, "Could not delete the note.") });
    }
  };

  return (
    <section aria-label="Project notes for the AI" className="space-y-1">
      <h3 className="text-[11px] font-semibold text-fg-muted">Project notes for the AI</h3>
      <p className="text-[10px] text-fg-subtle">
        Conventions and decisions the agent should follow in this project. Only you can add them;
        text that looks like a password, key, or token is refused.
      </p>
      {items.state === "error" && (
        <p role="alert" className="text-[11px] text-danger">
          {items.message}
        </p>
      )}
      {items.state === "ready" && (
        <ul className="space-y-0.5">
          {items.data.items.length === 0 && (
            <li className="text-[11px] text-fg-subtle">No notes yet.</li>
          )}
          {items.data.items.map((item) => (
            <li key={item.id} className="flex items-start gap-1.5 text-[11px] text-fg">
              <span className="shrink-0 text-fg-subtle">[{item.kind}]</span>
              <span className="min-w-0 flex-1">{item.text}</span>
              <button
                type="button"
                aria-label={`Delete note: ${item.text}`}
                ref={(button) => {
                  if (button) deleteButtons.current.set(item.id, button);
                  else deleteButtons.current.delete(item.id);
                }}
                onClick={() => void remove(item.id)}
                className="shrink-0 text-fg-subtle hover:text-danger"
              >
                <Trash2 aria-hidden className="size-3.5" />
              </button>
            </li>
          ))}
        </ul>
      )}
      <form onSubmit={add} className="flex flex-wrap items-center gap-1">
        <label htmlFor={kindId} className="sr-only">
          Note kind
        </label>
        <select
          id={kindId}
          value={kind}
          onChange={(e) => setKind(e.target.value as MemoryKind)}
          className="rounded border border-border bg-surface px-1 py-0.5 text-[11px] text-fg"
        >
          {MEMORY_KINDS.map((k) => (
            <option key={k} value={k}>
              {k}
            </option>
          ))}
        </select>
        <label htmlFor={textId} className="sr-only">
          Note text
        </label>
        <input
          id={textId}
          ref={textInput}
          value={text}
          onChange={(e) => onTextChange(e.target.value)}
          maxLength={500}
          placeholder="e.g. Use Pydantic models for request validation"
          className="min-w-0 flex-1 rounded border border-border bg-surface px-1.5 py-0.5 text-[11px] text-fg"
        />
        <button
          type="submit"
          disabled={text.trim().length < 3}
          className="rounded border border-border px-2 py-0.5 text-[11px] text-fg hover:bg-surface-hover disabled:opacity-50"
        >
          Save note
        </button>
      </form>
      {error && (
        <p role="alert" className="text-[11px] text-danger">
          {error.message}
        </p>
      )}
    </section>
  );
}

/**
 * Module 17: deterministic project insights (architecture, impact of a change) and the project notes
 * the agent follows. Works without an AI provider.
 */
export function InsightsPanel() {
  const { state } = useWorkspace();
  const projectId = state.project?.serverProjectId;
  const activePath = state.activePath;
  const [architecture, setArchitecture] = useState<Remote<Architecture>>({ state: "idle" });
  const [impact, setImpact] = useState<Remote<Impact>>({ state: "idle" });
  const [symbol, setSymbol] = useState("");
  const symbolId = useId();

  const loadArchitecture = async () => {
    if (!projectId) return;
    setArchitecture({ state: "loading" });
    try {
      setArchitecture({ state: "ready", data: await getArchitecture(projectId) });
    } catch (e) {
      setArchitecture({
        state: "error",
        message: message(e, "Could not analyze the architecture."),
      });
    }
  };
  const analyze = async (event: FormEvent) => {
    event.preventDefault();
    if (!projectId || !activePath) return;
    setImpact({ state: "loading" });
    try {
      setImpact({
        state: "ready",
        data: await getImpact(projectId, activePath, symbol.trim() || null),
      });
    } catch (e) {
      setImpact({ state: "error", message: message(e, "Could not analyze the impact.") });
    }
  };

  if (!projectId) {
    return (
      <p className="p-2 text-xs text-fg-muted">
        Insights work on projects stored on the server. Open one from the Projects area.
      </p>
    );
  }
  return (
    <div className="grid h-full min-h-0 grid-cols-1 gap-3 overflow-auto p-2 md:grid-cols-2">
      <section aria-label="Impact analysis" aria-live="polite" className="space-y-1.5">
        <h3 className="text-[11px] font-semibold text-fg-muted">What could break?</h3>
        <form onSubmit={analyze} className="flex flex-wrap items-center gap-1">
          <span className="truncate font-mono text-[11px] text-fg" title={activePath ?? undefined}>
            {activePath ?? "Open a file first"}
          </span>
          <label htmlFor={symbolId} className="sr-only">
            Symbol (optional)
          </label>
          <input
            id={symbolId}
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            placeholder="symbol (optional)"
            maxLength={200}
            className="w-36 rounded border border-border bg-surface px-1.5 py-0.5 font-mono text-[11px] text-fg"
          />
          <button
            type="submit"
            disabled={!activePath || impact.state === "loading"}
            className="rounded border border-border px-2 py-0.5 text-[11px] text-fg hover:bg-surface-hover disabled:opacity-50"
          >
            Analyze impact
          </button>
        </form>
        {impact.state === "loading" && (
          <p role="status" className="flex items-center gap-1 text-[11px] text-fg-muted">
            <Loader2 aria-hidden className="size-3.5 animate-spin" /> Analyzing…
          </p>
        )}
        {impact.state === "error" && (
          <p role="alert" className="text-[11px] text-danger">
            {impact.message}
          </p>
        )}
        {impact.state === "ready" && <ImpactView impact={impact.data} />}
        <ProjectNotes key={projectId} projectId={projectId} />
      </section>
      <section aria-label="Architecture" aria-live="polite" className="space-y-1.5">
        <div className="flex items-center gap-2">
          <h3 className="text-[11px] font-semibold text-fg-muted">Architecture</h3>
          <button
            type="button"
            onClick={() => void loadArchitecture()}
            disabled={architecture.state === "loading"}
            className="rounded border border-border px-2 py-0.5 text-[11px] text-fg hover:bg-surface-hover disabled:opacity-50"
          >
            {architecture.state === "ready" ? "Refresh" : "Analyze architecture"}
          </button>
        </div>
        {architecture.state === "loading" && (
          <p role="status" className="flex items-center gap-1 text-[11px] text-fg-muted">
            <Loader2 aria-hidden className="size-3.5 animate-spin" /> Analyzing…
          </p>
        )}
        {architecture.state === "error" && (
          <p role="alert" className="text-[11px] text-danger">
            {architecture.message}
          </p>
        )}
        {architecture.state === "ready" && <ArchitectureView data={architecture.data} />}
      </section>
    </div>
  );
}
