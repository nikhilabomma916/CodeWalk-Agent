"use client";

import { RefreshCw } from "lucide-react";
import { useEffect, useMemo, type ReactNode } from "react";

import { StateMessage } from "@/components/ui/state-message";
import { useWorkspace } from "@/features/workspace/workspace-context";
import type { IntelligenceSymbol, ProjectIntelligence } from "@/services/api/intelligence";

const KIND_LABEL: Record<IntelligenceSymbol["kind"], string> = {
  class: "class",
  function: "fn",
  method: "method",
  interface: "interface",
  type_alias: "type",
  enum: "enum",
  variable: "var",
};

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="min-w-0">
      <h3 className="mb-1 text-[11px] font-semibold tracking-wider text-fg-muted uppercase">
        {title}
      </h3>
      {children}
    </section>
  );
}

function FileLink({ path, onOpen }: { path: string; onOpen(path: string): void }) {
  return (
    <button
      type="button"
      onClick={() => onOpen(path)}
      className="truncate text-left font-mono text-accent hover:underline"
      title={`Open ${path}`}
    >
      {path}
    </button>
  );
}

function ActiveFile({
  data,
  path,
  onOpen,
  onReveal,
}: {
  data: ProjectIntelligence;
  path: string;
  onOpen(path: string): void;
  onReveal(path: string, line: number, column: number): void;
}) {
  const file = data.files.find((f) => f.path === path);
  const importedBy = useMemo(
    () =>
      [
        ...new Set(
          data.relationships
            .filter((r) => r.kind === "imports" && r.target_kind === "file" && r.target === path)
            .map((r) => r.source),
        ),
      ].sort(),
    [data.relationships, path],
  );

  if (!file) {
    return (
      <p className="text-fg-muted">
        This file was not part of the last analysis. Re-analyze to include it.
      </p>
    );
  }
  if (!file.structure_supported) {
    return (
      <p className="text-fg-muted">
        Structure is extracted for Python, JavaScript and TypeScript files.
      </p>
    );
  }
  return (
    <div className="grid gap-4 md:grid-cols-3">
      <Section title={`Outline (${file.symbols.length})`}>
        {file.symbols.length === 0 ? (
          <p className="text-fg-muted">No symbols.</p>
        ) : (
          <ul className="space-y-0.5">
            {file.symbols.map((symbol) => (
              <li
                key={symbol.id}
                style={{ paddingLeft: `${symbol.qualified_name.split(".").length * 8 - 8}px` }}
              >
                <button
                  type="button"
                  onClick={() => onReveal(path, symbol.line, symbol.column)}
                  className="flex w-full min-w-0 gap-1.5 text-left hover:text-fg"
                  title={symbol.signature ?? symbol.name}
                >
                  <span className="w-12 shrink-0 text-fg-subtle">{KIND_LABEL[symbol.kind]}</span>
                  <span className="truncate font-mono text-fg">
                    {symbol.is_async ? "async " : ""}
                    {symbol.name}
                  </span>
                  <span className="ml-auto shrink-0 text-fg-subtle">:{symbol.line}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </Section>
      <Section title={`Imports (${file.imports.length})`}>
        {file.imports.length === 0 ? (
          <p className="text-fg-muted">No imports.</p>
        ) : (
          <ul className="space-y-0.5">
            {file.imports.map((record, index) => (
              <li key={`${record.module}-${record.line}-${index}`} className="flex min-w-0 gap-2">
                <span className="w-8 shrink-0 text-fg-subtle">:{record.line}</span>
                {record.resolved_path ? (
                  <FileLink path={record.resolved_path} onOpen={onOpen} />
                ) : (
                  <span
                    className="truncate font-mono text-fg-muted"
                    title="External or unresolved module"
                  >
                    {`${".".repeat(record.level)}${record.module}`}{" "}
                    <span className="text-fg-subtle">(external)</span>
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}
      </Section>
      <Section title={`Imported by (${importedBy.length})`}>
        {importedBy.length === 0 ? (
          <p className="text-fg-muted">No project file imports this file.</p>
        ) : (
          <ul className="space-y-0.5">
            {importedBy.map((source) => (
              <li key={source} className="min-w-0">
                <FileLink path={source} onOpen={onOpen} />
              </li>
            ))}
          </ul>
        )}
      </Section>
    </div>
  );
}

export function IntelligencePanel() {
  const { state, actions } = useWorkspace();
  const { project, intelligence, activePath } = state;
  const serverProjectId = project?.serverProjectId;

  // Load stored results once per opened server project.
  useEffect(() => {
    if (serverProjectId && state.intelligence.status === "idle") void actions.loadIntelligence();
  }, [actions, serverProjectId, state.intelligence.status]);

  if (!project?.serverProjectId) {
    return (
      <StateMessage title="Project intelligence runs on server projects.">
        Create or open a project stored on the server to analyze its files, symbols, and imports.
      </StateMessage>
    );
  }

  const analyzing = intelligence.status === "loading";
  const header = (
    <div className="flex shrink-0 items-center gap-2 border-b border-border px-3 py-1 text-[11px] text-fg-muted">
      <span className="min-w-0 flex-1 truncate">
        {intelligence.status === "ready"
          ? `Analyzed ${new Date(intelligence.data.analyzed_at).toLocaleString()}${
              intelligence.data.sync
                ? ` · rescan: ${intelligence.data.sync.created} new, ${intelligence.data.sync.updated} changed, ${intelligence.data.sync.deleted} removed`
                : ""
            }`
          : "Deterministic analysis of files, symbols, imports, and relationships."}
      </span>
      <button
        type="button"
        onClick={() => void actions.analyzeServerProject()}
        disabled={analyzing}
        className="inline-flex items-center gap-1 rounded border border-border px-2 py-0.5 text-fg hover:bg-surface-hover disabled:opacity-50"
      >
        <RefreshCw aria-hidden className={`size-3 ${analyzing ? "animate-spin" : ""}`} />
        {analyzing ? "Analyzing…" : project.rootPath ? "Rescan & analyze" : "Analyze project"}
      </button>
    </div>
  );

  let body: ReactNode;
  if (intelligence.status === "idle" || intelligence.status === "loading") {
    body = <StateMessage title={analyzing ? "Analyzing project…" : "Loading…"} />;
  } else if (intelligence.status === "error") {
    body = (
      <StateMessage tone="error" title="Project analysis is unavailable.">
        {intelligence.message}
      </StateMessage>
    );
  } else if (intelligence.status === "empty") {
    body = (
      <StateMessage title="This project has not been analyzed yet.">
        Run “Analyze project”.
      </StateMessage>
    );
  } else {
    const { data } = intelligence;
    const stats = data.statistics;
    body = (
      <div className="min-h-0 flex-1 space-y-4 overflow-auto px-3 py-2 text-xs">
        <dl className="flex flex-wrap gap-x-5 gap-y-1">
          {[
            ["Files", stats.total_files],
            ["Folders", stats.total_directories],
            ["Lines", stats.total_lines.toLocaleString()],
            ["Size", formatBytes(stats.total_bytes)],
            ["Symbols", stats.total_symbols],
            ["Imports", `${stats.internal_imports} internal · ${stats.external_imports} external`],
            ["Parse errors", stats.analysis_errors],
          ].map(([label, value]) => (
            <div key={label} className="flex gap-1.5">
              <dt className="text-fg-muted">{label}</dt>
              <dd className="font-medium text-fg">{value}</dd>
            </div>
          ))}
        </dl>

        {activePath && (
          <Section title={`Active file · ${activePath}`}>
            <ActiveFile
              data={data}
              path={activePath}
              onOpen={(path) => void actions.openFile(path)}
              onReveal={(path, line, column) => void actions.revealPosition(path, line, column)}
            />
          </Section>
        )}

        <div className="grid gap-4 md:grid-cols-3">
          <Section title="Languages">
            <table className="w-full">
              <tbody>
                {stats.languages.map((language) => (
                  <tr key={language.language}>
                    <td className="py-px text-fg">{language.language}</td>
                    <td className="py-px text-right text-fg-muted">{language.files} files</td>
                    <td className="py-px text-right text-fg-muted">
                      {language.lines.toLocaleString()} lines
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Section>
          <Section title="Largest files">
            <ul className="space-y-0.5">
              {stats.largest_files.map((file) => (
                <li key={file.path} className="flex min-w-0 gap-2">
                  <FileLink path={file.path} onOpen={(path) => void actions.openFile(path)} />
                  <span className="ml-auto shrink-0 text-fg-muted">{formatBytes(file.size)}</span>
                </li>
              ))}
            </ul>
          </Section>
          <Section title={`Files that failed to parse (${data.errors.length})`}>
            {data.errors.length === 0 ? (
              <p className="text-fg-muted">None.</p>
            ) : (
              <ul className="space-y-1">
                {data.errors.map((error) => (
                  <li key={`${error.path}-${error.stage}`}>
                    <FileLink path={error.path} onOpen={(path) => void actions.openFile(path)} />
                    <span className="block text-fg-muted">{error.message}</span>
                  </li>
                ))}
              </ul>
            )}
          </Section>
        </div>
      </div>
    );
  }

  return (
    <section aria-label="Project intelligence" className="flex h-full min-h-0 flex-col">
      {header}
      {body}
    </section>
  );
}
