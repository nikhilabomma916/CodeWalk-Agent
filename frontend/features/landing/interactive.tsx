"use client";

import {
  BrainCircuit,
  Bug,
  Database,
  FileDiff,
  Network,
  NotebookPen,
  Search,
  Sparkles,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { useId, useState } from "react";

import styles from "./landing.module.css";

// --- Feature ecosystem --------------------------------------------------------------------------

interface Capability {
  id: string;
  name: string;
  icon: LucideIcon;
  summary: string;
  detail: string;
  /** Position around the centre, in percent of the diagram. */
  x: number;
  y: number;
}

const CAPABILITIES: Capability[] = [
  {
    id: "analysis",
    name: "AI Analysis",
    icon: Sparkles,
    summary: "Reviews a file for real issues.",
    detail:
      "Checks the open file for bugs, security, quality and performance problems, grounded in the code and its diagnostics, and explains each finding.",
    x: 50,
    y: 8,
  },
  {
    id: "diagnostics",
    name: "Diagnostics",
    icon: Bug,
    summary: "Problems while you type.",
    detail:
      "Static analysis runs as you edit: syntax errors, undefined names and lint findings appear inline and in the Problems panel. Code is analyzed, never executed.",
    x: 80,
    y: 22,
  },
  {
    id: "intelligence",
    name: "Project Intelligence",
    icon: Network,
    summary: "Symbols, imports, relationships.",
    detail:
      "Indexes files, languages, symbols and imports, resolves how files depend on each other, and summarizes architecture and the impact of a change.",
    x: 86,
    y: 55,
  },
  {
    id: "search",
    name: "Search",
    icon: Search,
    summary: "Beyond file names.",
    detail:
      "Finds functions, classes, imports, identifiers and text across the project, with a deterministic ranking that explains why each result matched.",
    x: 74,
    y: 88,
  },
  {
    id: "rag",
    name: "RAG",
    icon: Database,
    summary: "Retrieves what a question needs.",
    detail:
      "Code is embedded into PostgreSQL with pgvector; semantic and hybrid search retrieve only the snippets relevant to the question instead of sending the whole project.",
    x: 26,
    y: 88,
  },
  {
    id: "memory",
    name: "Project Memory",
    icon: NotebookPen,
    summary: "Conventions the AI follows.",
    detail:
      "Short notes you save for a project (conventions, decisions, terms) that the agent follows. Text that looks like a credential is refused.",
    x: 14,
    y: 55,
  },
  {
    id: "agents",
    name: "Agents",
    icon: BrainCircuit,
    summary: "Bounded, tool-using workflows.",
    detail:
      "Ask, review, tests, documentation, refactoring, impact and architecture workflows. The agent reads through read-only tools within step and token limits.",
    x: 20,
    y: 22,
  },
  {
    id: "fixes",
    name: "Reviewable Fixes",
    icon: FileDiff,
    summary: "Every change is a proposal.",
    detail:
      "Suggested changes arrive as diffs. Nothing is written until you approve, and a proposal for a file that changed since is reported as stale instead of applied.",
    x: 50,
    y: 100,
  },
];

export function FeatureEcosystem() {
  const [selected, setSelected] = useState(CAPABILITIES[0].id);
  const detailId = useId();
  const current = CAPABILITIES.find((c) => c.id === selected) ?? CAPABILITIES[0];

  const node = (c: Capability, compact = false, key?: string) => {
    const Icon = c.icon;
    const isSelected = c.id === selected;
    return (
      <button
        key={key}
        type="button"
        aria-pressed={isSelected}
        aria-controls={detailId}
        onClick={() => setSelected(c.id)}
        onMouseEnter={() => setSelected(c.id)}
        onFocus={() => setSelected(c.id)}
        className={`flex items-center gap-2 rounded-md border px-2.5 py-1.5 text-left text-[13px] whitespace-nowrap transition-colors ${
          isSelected
            ? "border-accent bg-surface-raised text-fg shadow-[0_0_0_3px_var(--color-accent-muted)]"
            : "border-border bg-surface text-fg-muted hover:border-border-strong hover:text-fg"
        } ${compact ? "w-full" : ""}`}
      >
        <Icon
          aria-hidden
          className={`size-4 shrink-0 ${isSelected ? "text-accent" : "text-fg-subtle"}`}
        />
        {c.name}
      </button>
    );
  };

  return (
    <div className="grid grid-cols-1 items-center gap-10 lg:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]">
      {/* Diagram (tablet and up). */}
      <div className="relative mx-auto hidden aspect-[1.35] w-full max-w-2xl sm:block">
        <svg
          aria-hidden
          viewBox="0 0 100 100"
          preserveAspectRatio="none"
          className="absolute inset-0 size-full"
        >
          {CAPABILITIES.map((c) => (
            <line
              key={c.id}
              x1="50"
              y1="54"
              x2={c.x}
              y2={c.y}
              pathLength={1}
              vectorEffect="non-scaling-stroke"
              className={`${styles.line} ${styles.drawOnView} transition-[stroke] duration-200`}
              stroke={c.id === selected ? "var(--color-accent)" : "var(--color-border-strong)"}
              strokeWidth={c.id === selected ? 1.5 : 1}
            />
          ))}
        </svg>
        <div className="absolute top-[54%] left-1/2 -translate-x-1/2 -translate-y-1/2">
          <div className="rounded-lg border border-border-strong bg-surface-raised px-4 py-3 text-center shadow-[0_18px_40px_-24px_rgb(0_0_0/0.5)]">
            <p className="text-[10px] font-semibold tracking-[0.18em] text-fg-subtle uppercase">
              One system
            </p>
            <p className="mt-0.5 text-sm font-semibold tracking-tight text-fg">CodeWalk Agent</p>
          </div>
        </div>
        {CAPABILITIES.map((c) => (
          <div
            key={c.id}
            className="absolute -translate-x-1/2 -translate-y-1/2"
            style={{ left: `${c.x}%`, top: `${c.y}%` }}
          >
            {node(c)}
          </div>
        ))}
      </div>

      {/* List (phones). */}
      <div className="grid grid-cols-2 gap-2 sm:hidden">
        {CAPABILITIES.map((c) => node(c, true, c.id))}
      </div>

      <div
        id={detailId}
        role="region"
        aria-live="polite"
        aria-label={`${current.name} details`}
        className="lg:pl-4"
      >
        <p className="text-[11px] font-semibold tracking-[0.18em] text-accent-text uppercase">
          {current.name}
        </p>
        <p className="mt-2 text-2xl font-semibold tracking-tight text-fg">{current.summary}</p>
        <p className="mt-3 max-w-md text-[15px] leading-relaxed text-fg-muted">{current.detail}</p>
        <p className="mt-6 text-xs text-fg-subtle">
          Select a capability to see how it fits. Each one feeds the same project context.
        </p>
      </div>
    </div>
  );
}

// --- Project intelligence graph -----------------------------------------------------------------

interface GraphNode {
  id: string;
  file: string;
  symbol: string;
  role: string;
  x: number;
  y: number;
  relations: string[];
}

const NODES: GraphNode[] = [
  {
    id: "route",
    file: "api/auth.py",
    symbol: "login()",
    role: "HTTP route · POST /login",
    x: 50,
    y: 10,
    relations: ["imports services/auth.py (confirmed)"],
  },
  {
    id: "service",
    file: "services/auth.py",
    symbol: "AuthService.authenticate()",
    role: "Service",
    x: 50,
    y: 42,
    relations: [
      "imported by api/auth.py (confirmed)",
      "imports models/user.py (confirmed)",
      "imports db/session.py (confirmed)",
      "related test: tests/test_auth.py",
    ],
  },
  {
    id: "model",
    file: "models/user.py",
    symbol: "User",
    role: "Data model · __tablename__ users",
    x: 22,
    y: 74,
    relations: ["imported by services/auth.py (confirmed)", "imports db/session.py (confirmed)"],
  },
  {
    id: "session",
    file: "db/session.py",
    symbol: "get_session()",
    role: "Database access",
    x: 78,
    y: 74,
    relations: ["imported by services/auth.py and models/user.py (confirmed)"],
  },
  {
    id: "test",
    file: "tests/test_auth.py",
    symbol: "test_rejects_bad_token()",
    role: "Test",
    x: 86,
    y: 30,
    relations: ["imports services/auth.py (confirmed)"],
  },
];

const EDGES: [string, string][] = [
  ["route", "service"],
  ["service", "model"],
  ["service", "session"],
  ["model", "session"],
  ["test", "service"],
];

export function ProjectGraph() {
  const [selected, setSelected] = useState("service");
  const detailId = useId();
  const current = NODES.find((n) => n.id === selected) ?? NODES[1];
  const at = (id: string) => NODES.find((n) => n.id === id)!;
  const touches = (edge: [string, string]) => edge.includes(selected);

  return (
    <div className="grid grid-cols-1 gap-8 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)] lg:items-center">
      <div className="relative rounded-lg border border-border bg-surface p-3">
        <p className="absolute top-3 left-4 text-[10px] tracking-[0.16em] text-fg-subtle uppercase">
          Example project relationship
        </p>
        <div className="relative mt-6 aspect-[1.7] w-full">
          <svg
            aria-hidden
            viewBox="0 0 100 100"
            preserveAspectRatio="none"
            className="absolute inset-0 size-full"
          >
            {EDGES.map((edge) => {
              const [a, b] = edge.map(at);
              const on = touches(edge);
              return (
                <line
                  key={edge.join("-")}
                  x1={a.x}
                  y1={a.y}
                  x2={b.x}
                  y2={b.y}
                  pathLength={1}
                  vectorEffect="non-scaling-stroke"
                  className={`${styles.line} ${styles.drawOnView}`}
                  stroke={on ? "var(--color-accent)" : "var(--color-border-strong)"}
                  strokeWidth={on ? 1.75 : 1}
                />
              );
            })}
          </svg>
          {NODES.map((n) => {
            const isSelected = n.id === selected;
            return (
              <button
                key={n.id}
                type="button"
                aria-pressed={isSelected}
                aria-controls={detailId}
                onClick={() => setSelected(n.id)}
                onMouseEnter={() => setSelected(n.id)}
                onFocus={() => setSelected(n.id)}
                style={{ left: `${n.x}%`, top: `${n.y}%` }}
                className={`absolute -translate-x-1/2 -translate-y-1/2 rounded border px-2 py-1 font-mono text-[10.5px] whitespace-nowrap transition-colors sm:text-xs ${
                  isSelected
                    ? "border-accent bg-surface-raised text-fg shadow-[0_0_0_3px_var(--color-accent-muted)]"
                    : "border-border bg-surface-sunken text-fg-muted hover:border-border-strong hover:text-fg"
                }`}
              >
                {n.file}
              </button>
            );
          })}
        </div>
      </div>

      <dl
        id={detailId}
        aria-live="polite"
        className="grid grid-cols-[6.5rem_minmax(0,1fr)] gap-x-4 gap-y-3 rounded-lg border border-border bg-surface-sunken p-5 text-sm [&_dd]:min-w-0 [&_dd]:break-words"
      >
        <dt className="text-xs tracking-wide text-fg-subtle uppercase">File</dt>
        <dd className="font-mono break-all text-fg">{current.file}</dd>
        <dt className="text-xs tracking-wide text-fg-subtle uppercase">Symbol</dt>
        <dd className="font-mono break-all text-fg">{current.symbol}</dd>
        <dt className="text-xs tracking-wide text-fg-subtle uppercase">Role</dt>
        <dd className="text-fg-muted">{current.role}</dd>
        <dt className="text-xs tracking-wide text-fg-subtle uppercase">Relationships</dt>
        <dd>
          <ul className="space-y-1 text-fg-muted">
            {current.relations.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        </dd>
        <dd className="col-span-2 border-t border-border pt-3 text-xs leading-relaxed text-fg-subtle">
          CodeWalk links files through resolved imports (confirmed) and marks same-name mentions as
          possible. It does not claim a call graph or type analysis.
        </dd>
      </dl>
    </div>
  );
}

// --- Ask your project ---------------------------------------------------------------------------

interface Example {
  question: string;
  context: string[];
  answer: string;
}

const EXAMPLES: Example[] = [
  {
    question: "What technologies are we using?",
    context: ["package.json", "pyproject.toml", "docker-compose.yml"],
    answer:
      "A Next.js + TypeScript frontend, a FastAPI service in Python, and PostgreSQL. Docker Compose runs the stack.",
  },
  {
    question: "How does authentication work?",
    context: ["api/auth.py", "services/auth.py", "models/user.py"],
    answer:
      "POST /login calls AuthService.authenticate() (services/auth.py:18), which checks the password hash on User and stores a server-side session.",
  },
  {
    question: "What changed recently?",
    context: ["project activity (last 7 days)"],
    answer:
      "services/auth.py was edited twice and re-analyzed; one proposed fix to models/user.py was approved; tests/test_auth.py was added.",
  },
  {
    question: "Which files handle authentication?",
    context: ["search: auth", "imports of services/auth.py"],
    answer:
      "api/auth.py (route), services/auth.py (logic), models/user.py (data), tests/test_auth.py (tests).",
  },
  {
    question: "Why is this function failing?",
    context: ["open file: services/auth.py", "diagnostic: line 22", "selected function"],
    answer:
      "Line 22 reads session_store, which is never defined or imported in this file. Import it from db/session.py or pass it in.",
  },
];

export function AskProject() {
  const [index, setIndex] = useState(1);
  const answerId = useId();
  const example = EXAMPLES[index];
  return (
    <div className="mx-auto max-w-3xl">
      <div
        role="group"
        aria-label="Example questions"
        className="flex flex-wrap justify-center gap-2"
      >
        {EXAMPLES.map((e, i) => (
          <button
            key={e.question}
            type="button"
            aria-pressed={i === index}
            aria-controls={answerId}
            onClick={() => setIndex(i)}
            className={`rounded-full border px-3.5 py-1.5 text-[13px] transition-colors ${
              i === index
                ? "border-accent bg-accent-muted text-fg"
                : "border-border bg-surface text-fg-muted hover:border-border-strong hover:text-fg"
            }`}
          >
            {e.question}
          </button>
        ))}
      </div>

      <div
        id={answerId}
        aria-live="polite"
        className="mt-8 overflow-hidden rounded-lg border border-border bg-surface shadow-[0_24px_60px_-34px_rgb(0_0_0/0.45)]"
      >
        <div className="flex items-center gap-2 border-b border-border bg-surface-sunken px-4 py-2.5">
          <Search aria-hidden className="size-4 text-fg-subtle" />
          <p className="truncate text-sm text-fg">{example.question}</p>
        </div>
        <div className="grid gap-4 p-4 sm:grid-cols-[11rem_1fr]">
          <div>
            <p className="text-[10px] tracking-[0.16em] text-fg-subtle uppercase">
              Context retrieved
            </p>
            <ul className="mt-2 space-y-1">
              {example.context.map((c) => (
                <li key={c} className="truncate font-mono text-[11.5px] text-fg-muted">
                  {c}
                </li>
              ))}
            </ul>
          </div>
          <div>
            <p className="text-[10px] tracking-[0.16em] text-fg-subtle uppercase">Answer</p>
            <p className="mt-2 text-[15px] leading-relaxed text-fg">{example.answer}</p>
          </div>
        </div>
        <p className="border-t border-border px-4 py-2 text-[11px] text-fg-subtle">
          Example answer for an example project. In CodeWalk, answers come from your own project.{" "}
          <Link href="/app/projects" className="text-accent-text hover:underline">
            Ask about yours
          </Link>
        </p>
      </div>
    </div>
  );
}
