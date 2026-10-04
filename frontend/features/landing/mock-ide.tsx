import { CircleAlert, CircleX, FileCode2, Sparkles, TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";

import { LogoMark } from "@/components/ui/logo";

import styles from "./landing.module.css";

/**
 * Static recreations of the CodeWalk workspace for the landing page (presentation only: no data,
 * no requests). They use the app's own tokens so they match the real product in both themes.
 */

const PY_KEYWORDS = new Set([
  "def",
  "return",
  "if",
  "not",
  "raise",
  "from",
  "import",
  "class",
  "None",
  "True",
  "False",
  "await",
  "async",
  "for",
  "in",
  "is",
  "and",
  "or",
  "with",
  "as",
]);

const TOKEN =
  /(#.*$)|("[^"]*"|'[^']*')|(\b\d+\b)|([A-Za-z_][A-Za-z0-9_]*)(?=\s*\()|([A-Za-z_][A-Za-z0-9_]*)|(\s+|.)/g;

/** A deliberately small Python highlighter: keywords, strings, numbers, comments, calls. */
export function highlight(line: string): ReactNode[] {
  const out: ReactNode[] = [];
  let match: RegExpExecArray | null;
  let i = 0;
  TOKEN.lastIndex = 0;
  while ((match = TOKEN.exec(line)) !== null) {
    const [text, comment, string, number, call, word] = match;
    const key = i++;
    if (comment)
      out.push(
        <span key={key} className="text-fg-subtle italic">
          {text}
        </span>,
      );
    else if (string)
      out.push(
        <span key={key} className="text-success">
          {text}
        </span>,
      );
    else if (number)
      out.push(
        <span key={key} className="text-warning">
          {text}
        </span>,
      );
    else if (call)
      out.push(
        <span key={key} className={PY_KEYWORDS.has(call) ? "text-accent-text" : "text-info"}>
          {text}
        </span>,
      );
    else if (word && PY_KEYWORDS.has(word))
      out.push(
        <span key={key} className="text-accent-text">
          {text}
        </span>,
      );
    else out.push(text);
    if (match.index === TOKEN.lastIndex) TOKEN.lastIndex++;
  }
  return out;
}

export type Mark = "error" | "warning";

export function CodeLines({
  lines,
  start = 1,
  marks = {},
  current,
  className = "",
}: {
  lines: string[];
  start?: number;
  /** Diagnostic underline per line number. */
  marks?: Record<number, Mark>;
  /** The line with the cursor. */
  current?: number;
  className?: string;
}) {
  return (
    <ol className={`font-mono text-[11.5px] leading-[1.7] sm:text-xs ${className}`}>
      {lines.map((line, index) => {
        const n = start + index;
        const mark = marks[n];
        return (
          <li
            key={n}
            className={`grid grid-cols-[2.25rem_1fr] pr-3 ${n === current ? "bg-surface-hover/60" : ""}`}
          >
            <span aria-hidden className="pr-3 text-right text-fg-subtle/70 select-none">
              {n}
            </span>
            <span
              className={`whitespace-pre ${
                mark === "error"
                  ? "underline decoration-danger decoration-wavy decoration-1 underline-offset-[5px]"
                  : mark === "warning"
                    ? "underline decoration-warning decoration-wavy decoration-1 underline-offset-[5px]"
                    : ""
              }`}
            >
              {highlight(line)}
              {line === "" ? " " : null}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

/** The app frame: the same header the real workspace shows (logo, project / file breadcrumb). */
export function MockWindow({
  project,
  file,
  children,
  className = "",
  label,
}: {
  project: string;
  file: string;
  children: ReactNode;
  className?: string;
  /** Accessible description of what the preview shows. */
  label: string;
}) {
  return (
    <figure
      aria-label={label}
      className={`overflow-hidden rounded-lg border border-border bg-surface shadow-[0_24px_60px_-28px_rgb(0_0_0/0.45)] ${className}`}
    >
      <div className="flex h-9 items-center gap-2 border-b border-border bg-surface-sunken px-3 text-[11px]">
        <LogoMark className="size-3.5" />
        <span className="font-semibold tracking-wide text-fg-muted uppercase">Coding</span>
        <span className="text-fg-subtle">/</span>
        <span className="truncate font-medium text-fg">{project}</span>
        <span className="rounded border border-border px-1 text-[9px] text-fg-subtle">Server</span>
        <span className="hidden truncate font-mono text-fg-muted sm:inline">/ {file}</span>
        <span className="flex-1" />
        <span className="flex items-center gap-1 text-fg-subtle">
          <span className={`size-1.5 rounded-full bg-success ${styles.live}`} aria-hidden />
          Analyzed
        </span>
      </div>
      {children}
    </figure>
  );
}

export function FileList({
  files,
  active,
  related = [],
  relatedClassName = "",
  title = "Code files",
}: {
  files: string[];
  active: string;
  related?: string[];
  relatedClassName?: string;
  title?: string;
}) {
  return (
    <div className="min-w-0 border-border bg-surface-sunken py-2">
      <p className="px-3 pb-1.5 text-[10px] font-semibold tracking-wider text-fg-muted uppercase">
        {title}
      </p>
      <ul className="space-y-px text-[11.5px]">
        {files.map((file) => {
          const isActive = file === active;
          const isRelated = related.includes(file);
          return (
            <li
              key={file}
              className={`flex items-center gap-1.5 px-3 py-[3px] font-mono ${
                isActive ? "bg-accent-muted text-fg" : "text-fg-muted"
              } ${isRelated ? `shadow-[inset_2px_0_0_var(--color-accent)] ${relatedClassName}` : ""}`}
            >
              <FileCode2
                aria-hidden
                className={`size-3 shrink-0 ${isActive ? "text-accent" : "text-fg-subtle"}`}
              />
              <span className="truncate">{file}</span>
              {isRelated && <span className="sr-only">(related)</span>}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export interface Problem {
  severity: "error" | "warning" | "info";
  message: string;
  source: string;
  location: string;
}

const SEVERITY = {
  error: { icon: CircleX, className: "text-danger", label: "Error" },
  warning: { icon: TriangleAlert, className: "text-warning", label: "Warning" },
  info: { icon: CircleAlert, className: "text-info", label: "Info" },
} as const;

export function ProblemsPanel({
  problems,
  className = "",
}: {
  problems: Problem[];
  className?: string;
}) {
  const errors = problems.filter((p) => p.severity === "error").length;
  const warnings = problems.filter((p) => p.severity === "warning").length;
  return (
    <div className={`border-t border-border bg-surface ${className}`}>
      <div className="flex items-center gap-3 border-b border-border px-3 py-1.5 text-[10px] font-semibold tracking-wider uppercase">
        <span className="border-b border-accent pb-px text-fg">Problems ({problems.length})</span>
        <span className="text-fg-subtle">Agent</span>
        <span className="hidden text-fg-subtle sm:inline">Insights</span>
        <span className="ml-auto font-normal tracking-normal text-fg-subtle normal-case">
          {errors} error{errors === 1 ? "" : "s"} · {warnings} warning{warnings === 1 ? "" : "s"}
        </span>
      </div>
      <ul className="py-1 text-[11.5px]">
        {problems.map((p) => {
          const { icon: Icon, className: tone, label } = SEVERITY[p.severity];
          return (
            <li key={p.message} className="flex items-center gap-2 px-3 py-[3px]">
              <Icon aria-label={label} className={`size-3.5 shrink-0 ${tone}`} />
              <span className="truncate text-fg">{p.message}</span>
              <span className="ml-auto hidden shrink-0 font-mono text-[10px] text-fg-subtle sm:inline">
                {p.source} {p.location}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export function AiPanel({
  context,
  children,
  className = "",
}: {
  context: string[];
  children: ReactNode;
  className?: string;
}) {
  return (
    <aside
      aria-label="AI assistance"
      className={`flex min-w-0 flex-col bg-surface-sunken ${className}`}
    >
      <p className="flex items-center gap-1.5 border-b border-border px-3 py-2 text-[10px] font-semibold tracking-wider text-fg-muted uppercase">
        <Sparkles aria-hidden className="size-3.5 text-accent" /> AI · Agent
      </p>
      <div className="space-y-2.5 p-3 text-[11.5px] leading-relaxed">
        <div>
          <p className="mb-1 text-[10px] tracking-wide text-fg-subtle uppercase">Context used</p>
          <ul className="flex flex-wrap gap-1">
            {context.map((c) => (
              <li
                key={c}
                className="rounded border border-border bg-surface px-1.5 py-px font-mono text-[10px] text-fg-muted"
              >
                {c}
              </li>
            ))}
          </ul>
        </div>
        {children}
      </div>
    </aside>
  );
}

/** A compact unified diff: removed and added lines are marked by sign and colour. */
export function MiniDiff({
  removed,
  added,
  file,
}: {
  removed: string[];
  added: string[];
  file: string;
}) {
  return (
    <div className="overflow-hidden rounded border border-border bg-surface font-mono text-[11px] leading-[1.65]">
      <p className="border-b border-border bg-surface-sunken px-2 py-1 text-[10px] text-fg-muted">
        {file}
      </p>
      {removed.map((line) => (
        <p key={`-${line}`} className="bg-danger/10 px-2 break-all whitespace-pre-wrap text-fg">
          <span aria-label="removed" className="mr-2 text-danger">
            −
          </span>
          {line}
        </p>
      ))}
      {added.map((line) => (
        <p key={`+${line}`} className="bg-success/10 px-2 break-all whitespace-pre-wrap text-fg">
          <span aria-label="added" className="mr-2 text-success">
            +
          </span>
          {line}
        </p>
      ))}
    </div>
  );
}
