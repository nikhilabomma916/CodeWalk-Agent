import {
  ArrowDown,
  ArrowRight,
  Check,
  ChevronDown,
  CircleX,
  FileCode2,
  Folder,
  Search,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { LogoMark } from "@/components/ui/logo";

import { AskProject, FeatureEcosystem, ProjectGraph } from "./interactive";
import styles from "./landing.module.css";
import { LANDING_SECTIONS } from "./landing-config";
import {
  AiPanel,
  CodeLines,
  FileList,
  MiniDiff,
  MockWindow,
  ProblemsPanel,
  type Problem,
} from "./mock-ide";

// --- Shared ----------------------------------------------------------------------------------------

const container = "mx-auto w-full max-w-7xl px-4 sm:px-6";
const wideContainer = "mx-auto w-full max-w-[88rem] px-4 sm:px-6";
const primaryCta =
  "group inline-flex items-center justify-center gap-2 rounded-md bg-accent px-5 py-3 text-sm font-semibold tracking-wide text-on-accent uppercase transition-colors hover:bg-accent-strong hover:text-on-accent-hover";
const secondaryCta =
  "inline-flex items-center justify-center gap-2 rounded-md border border-border-strong bg-surface px-5 py-3 text-sm font-semibold tracking-wide text-fg uppercase transition-colors hover:bg-surface-hover";

function Eyebrow({ children }: { children: ReactNode }) {
  return (
    <p className="font-mono text-[11px] font-medium tracking-[0.2em] text-accent-text uppercase">
      {children}
    </p>
  );
}

function SectionHeading({
  eyebrow,
  title,
  intro,
  align = "left",
  id,
}: {
  eyebrow: string;
  title: ReactNode;
  intro?: ReactNode;
  align?: "left" | "center";
  id: string;
}) {
  return (
    <div
      className={`${styles.reveal} max-w-3xl ${align === "center" ? "mx-auto text-center" : ""}`}
    >
      <Eyebrow>{eyebrow}</Eyebrow>
      <h2
        id={id}
        className="mt-3 text-3xl font-semibold tracking-[-0.025em] text-fg sm:text-[2.6rem] sm:leading-[1.08]"
      >
        {title}
      </h2>
      {intro && <p className="mt-4 text-[17px] leading-relaxed text-fg-muted">{intro}</p>}
    </div>
  );
}

const AUTH_CODE = [
  "from datetime import datetime",
  "from models import User",
  "from services import verify_token",
  "",
  "",
  "def authenticate_user(token: str) -> User:",
  '    """Return the user for a session token."""',
  "    if not token:",
  '        raise ValueError("missing token")',
  "    retries = 3",
  "    claims = verify_token(token)",
  '    user = session_store.get(claims["sub"])',
  "    if user is None:",
  '        raise PermissionError("unknown user")',
  "    return user",
];

const AUTH_PROBLEMS: Problem[] = [
  {
    severity: "error",
    message: "Undefined name `session_store`",
    source: "ruff(F821)",
    location: "12:12",
  },
  {
    severity: "warning",
    message: "`datetime.datetime` imported but unused",
    source: "ruff(F401)",
    location: "1:22",
  },
  {
    severity: "warning",
    message: "Local variable `retries` is assigned to but never used",
    source: "ruff(F841)",
    location: "10:5",
  },
];

// --- 2. Hero -------------------------------------------------------------------------------------

export function Hero() {
  return (
    <section id="home" aria-labelledby="hero-title" className="relative overflow-hidden">
      <div aria-hidden className={`pointer-events-none absolute inset-0 ${styles.grid}`} />
      <div
        className={`${wideContainer} relative grid grid-cols-1 gap-12 pt-14 pb-20 lg:grid-cols-[minmax(0,0.95fr)_minmax(0,1.25fr)] lg:items-center lg:gap-10 lg:pt-20 lg:pb-28`}
      >
        <div className={styles.heroText}>
          <Eyebrow>AI-powered development environment</Eyebrow>
          <h1
            id="hero-title"
            className="mt-5 text-[clamp(2.5rem,6.4vw,3.75rem)] leading-[1.02] font-semibold tracking-[-0.04em] text-fg"
          >
            Your Codebase.
            <br />
            <span className="text-accent lg:whitespace-nowrap">Understood by AI.</span>
          </h1>
          <p className="mt-6 max-w-xl text-lg leading-relaxed text-fg-muted">
            CodeWalk Agent connects your code, diagnostics, project structure, and AI assistance in
            one intelligent development workspace.
          </p>
          <div className="mt-8 flex flex-col gap-3 sm:flex-row">
            <Link href="/app/coding" className={primaryCta}>
              Open Workspace
              <ArrowRight
                aria-hidden
                className="size-4 transition-transform group-hover:translate-x-0.5"
              />
            </Link>
            <a href="#features" className={secondaryCta}>
              Explore Features
            </a>
          </div>
          <p className="mt-6 flex items-center gap-2 text-sm text-fg-subtle">
            <ShieldCheck aria-hidden className="size-4 text-accent" />
            AI assists. You stay in control.
          </p>
        </div>

        <MockWindow
          project="Payments API"
          file="auth.py"
          label="CodeWalk workspace preview: auth.py with one error and two warnings, and the AI explaining the error with a reviewable fix"
          className={styles.preview}
        >
          <div className="grid grid-cols-[minmax(0,1fr)] sm:grid-cols-[8.75rem_minmax(0,1fr)] xl:grid-cols-[8.75rem_minmax(0,1fr)_14.5rem]">
            <div className="hidden border-r border-border sm:block">
              <FileList
                files={["auth.py", "api.py", "models.py", "services.py", "utils.py"]}
                active="auth.py"
                related={["models.py", "services.py"]}
                relatedClassName={styles.stage3}
              />
            </div>
            <div className="min-w-0">
              <div className="flex h-8 items-end gap-px border-b border-border bg-surface-sunken pl-2">
                <span className="flex h-7 items-center gap-1.5 rounded-t border border-b-0 border-border bg-surface px-3 font-mono text-[11px] text-fg">
                  <FileCode2 aria-hidden className="size-3 text-accent" /> auth.py
                </span>
              </div>
              <div className={`overflow-x-auto py-2 ${styles.mockScroll}`}>
                <CodeLines
                  lines={AUTH_CODE}
                  marks={{ 1: "warning", 10: "warning", 12: "error" }}
                  current={12}
                />
              </div>
              <ProblemsPanel problems={AUTH_PROBLEMS} className={styles.stage1} />
            </div>
            <AiPanel
              context={["auth.py:12", "services.py", "models.py", "F821"]}
              className={`border-t border-border sm:col-span-2 xl:col-span-1 xl:border-t-0 xl:border-l ${styles.stage2}`}
            >
              <p className="text-fg">
                This function references an undefined variable:{" "}
                <code className="font-mono">session_store</code> is never defined or imported in{" "}
                <code className="font-mono">auth.py</code>.
              </p>
              <div>
                <p className="mb-1 text-[10px] tracking-wide text-fg-subtle uppercase">
                  Suggested fix
                </p>
                <MiniDiff
                  file="auth.py"
                  removed={['user = session_store.get(claims["sub"])']}
                  added={[
                    "from services import get_session",
                    'user = get_session().get(User, claims["sub"])',
                  ]}
                />
              </div>
              <p className="flex items-center gap-1.5 text-[11px] text-fg-subtle">
                <ShieldCheck aria-hidden className="size-3.5" /> Waiting for your review
              </p>
            </AiPanel>
          </div>
        </MockWindow>
      </div>
    </section>
  );
}

// --- 4. The problem --------------------------------------------------------------------------------

const TREE = [
  { name: "auth", related: true },
  { name: "services", related: true },
  { name: "api", related: true },
  { name: "database", related: true },
  { name: "tests", related: true },
  { name: "configuration", related: false },
];

export function ProblemSection() {
  return (
    <section
      aria-labelledby="problem-title"
      className="border-y border-border bg-surface-sunken py-24 sm:py-32"
    >
      <div className={container}>
        <h2 id="problem-title" className="sr-only">
          From one file to the whole project
        </h2>
        <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
          <div className={`${styles.reveal} rounded-lg border border-border bg-surface p-5 sm:p-8`}>
            <p className="text-[11px] font-semibold tracking-[0.18em] text-fg-subtle uppercase">
              A typical editor
            </p>
            <p className="mt-2 text-2xl font-semibold tracking-tight text-fg">
              Most editors see the file.
            </p>
            <div className="mt-8 flex h-44 items-center justify-center rounded-md border border-dashed border-border">
              <span className="flex items-center gap-2 rounded border border-border bg-surface-sunken px-3 py-2 font-mono text-sm text-fg-muted">
                <FileCode2 aria-hidden className="size-4" /> main.py
              </span>
            </div>
          </div>
          <div
            className={`${styles.reveal} relative rounded-lg border border-accent/50 bg-surface p-5 sm:p-8`}
          >
            <p className="text-[11px] font-semibold tracking-[0.18em] text-accent-text uppercase">
              CodeWalk Agent
            </p>
            <p className="mt-2 text-2xl font-semibold tracking-tight text-fg">
              CodeWalk Agent sees the project.
            </p>
            <div className="mt-8 grid h-48 grid-cols-[auto_minmax(1.25rem,1fr)_auto] items-stretch">
              <div className="flex items-center">
                <span className="flex items-center gap-2 rounded border border-accent bg-accent-muted px-3 py-2 font-mono text-sm text-fg">
                  <FileCode2 aria-hidden className="size-4 text-accent" /> main.py
                </span>
              </div>
              <svg
                aria-hidden
                viewBox="0 0 100 100"
                preserveAspectRatio="none"
                className="h-full w-full"
              >
                {TREE.map((t, i) => {
                  if (!t.related) return null;
                  // Rows are equal height: a "Project" header, then one row per folder.
                  const y = ((i + 1.5) / (TREE.length + 1)) * 100;
                  return (
                    <path
                      key={t.name}
                      d={`M0 50 C 45 50, 55 ${y}, 100 ${y}`}
                      fill="none"
                      stroke="var(--color-accent)"
                      strokeOpacity="0.75"
                      vectorEffect="non-scaling-stroke"
                      pathLength={1}
                      className={`${styles.line} ${styles.drawOnView}`}
                    />
                  );
                })}
              </svg>
              <ul className="flex h-full flex-col font-mono text-xs sm:text-sm">
                <li className="flex flex-1 items-center text-[11px] tracking-[0.16em] text-fg-subtle uppercase">
                  Project
                </li>
                {TREE.map((t, i) => (
                  <li
                    key={t.name}
                    className={`flex flex-1 items-center gap-1.5 ${t.related ? "text-fg" : "text-fg-subtle"}`}
                  >
                    <span aria-hidden className="text-fg-subtle">
                      {i === TREE.length - 1 ? "└──" : "├──"}
                    </span>
                    <Folder
                      aria-hidden
                      className={`size-3.5 ${t.related ? "text-accent" : "text-fg-subtle"}`}
                    />
                    {t.name}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>
        <p
          className={`${styles.reveal} mx-auto mt-20 max-w-4xl text-center text-[clamp(1.9rem,4.4vw,3.4rem)] leading-[1.1] font-semibold tracking-[-0.03em] text-fg`}
        >
          Understand the code.
          <br />
          <span className="text-fg-muted">Understand the project.</span>
          <br />
          <span className="text-accent">Understand the problem.</span>
        </p>
      </div>
    </section>
  );
}

// --- 5. Code → context -----------------------------------------------------------------------------

export function ContextFlow() {
  const steps: { n: string; title: string; body: ReactNode }[] = [
    {
      n: "01",
      title: "Code",
      body: <CodeLines lines={["user = authenticate(token)"]} start={27} className="-mx-1" />,
    },
    {
      n: "02",
      title: "Diagnostic",
      body: (
        <p className="flex items-center gap-1.5 text-[13px] text-fg">
          <CircleX aria-label="Error" className="size-4 text-danger" /> Undefined name
          <span className="ml-auto font-mono text-[10px] text-fg-subtle">27:8</span>
        </p>
      ),
    },
    {
      n: "03",
      title: "Project context",
      body: (
        <ul className="space-y-0.5 font-mono text-[12px] text-fg-muted">
          {["auth.py", "services/user.py", "models/user.py"].map((f) => (
            <li key={f} className="flex items-center gap-1.5">
              <FileCode2 aria-hidden className="size-3 text-accent" />
              {f}
            </li>
          ))}
        </ul>
      ),
    },
    {
      n: "04",
      title: "AI understanding",
      body: (
        <p className="text-[13px] leading-relaxed text-fg">
          “The function depends on <code className="font-mono">authenticate</code> from
          services/user.py, which this file never imports.”
        </p>
      ),
    },
    {
      n: "05",
      title: "Reviewable suggestion",
      body: (
        <MiniDiff file="main.py" removed={[]} added={["from services.user import authenticate"]} />
      ),
    },
  ];
  return (
    <section aria-labelledby="flow-title" className="py-24 sm:py-32">
      <div className={container}>
        <SectionHeading
          id="flow-title"
          eyebrow="From code to context"
          title="One line of code, followed all the way to a fix you can review."
          intro="CodeWalk connects what you are editing with what it means for the rest of the project, then lets AI explain it and propose a change."
        />
        <ol className="mt-14 grid grid-cols-1 gap-3 lg:grid-cols-5">
          {steps.map((s, i) => (
            <li key={s.n} className={`${styles.reveal} relative flex flex-col`}>
              <div className="flex items-center gap-2 pb-3">
                <span className="font-mono text-[11px] text-accent-text">{s.n}</span>
                <span className="text-[11px] font-semibold tracking-[0.16em] text-fg-muted uppercase">
                  {s.title}
                </span>
              </div>
              <div className="min-h-[7.5rem] flex-1 rounded-lg border border-border bg-surface p-3">
                {s.body}
              </div>
              {i < steps.length - 1 && (
                <>
                  <ArrowRight
                    aria-hidden
                    className="absolute top-1/2 -right-3 z-10 hidden size-4 text-fg-subtle lg:block"
                  />
                  <ArrowDown aria-hidden className="mx-auto mt-2 size-4 text-fg-subtle lg:hidden" />
                </>
              )}
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

// --- 6–7. Features ------------------------------------------------------------------------------------

export function Features() {
  return (
    <section
      id="features"
      aria-labelledby="features-title"
      className="border-t border-border bg-surface-sunken py-24 sm:py-32"
    >
      <div className={container}>
        <SectionHeading
          id="features-title"
          eyebrow="Feature ecosystem"
          title="Connected parts of one system, not a list of tools."
          intro="Every capability reads from and writes to the same project understanding."
        />
        <div className="mt-14">
          <FeatureEcosystem />
        </div>
      </div>
      <Spotlights />
    </section>
  );
}

function Story({
  eyebrow,
  title,
  body,
  visual,
  flip = false,
}: {
  eyebrow: string;
  title: string;
  body: string;
  visual: ReactNode;
  flip?: boolean;
}) {
  return (
    <article className="grid grid-cols-1 items-center gap-10 lg:grid-cols-2 lg:gap-16">
      <div className={`${styles.reveal} ${flip ? "lg:order-2" : ""}`}>{visual}</div>
      <div className={`${styles.reveal} ${flip ? "lg:order-1" : ""}`}>
        <Eyebrow>{eyebrow}</Eyebrow>
        <h3 className="mt-3 text-2xl font-semibold tracking-[-0.02em] text-fg sm:text-3xl">
          {title}
        </h3>
        <p className="mt-4 max-w-lg text-[16px] leading-relaxed text-fg-muted">{body}</p>
      </div>
    </article>
  );
}

function Spotlights() {
  return (
    <div className={`${container} mt-28 space-y-28`}>
      <Story
        eyebrow="Real-time diagnostics"
        title="See problems while you code."
        body="As you type, static analysis checks the open file: syntax errors, undefined names and lint findings are underlined in the editor and listed in Problems with their exact location. Nothing is run."
        visual={
          <div className="overflow-hidden rounded-lg border border-border bg-surface">
            <div className={`overflow-x-auto py-2 ${styles.mockScroll}`}>
              <CodeLines
                lines={AUTH_CODE.slice(9, 13)}
                start={10}
                marks={{ 10: "warning", 12: "error" }}
                current={12}
              />
            </div>
            <ProblemsPanel problems={AUTH_PROBLEMS.filter((p) => p.location !== "1:22")} />
          </div>
        }
      />
      <Story
        flip
        eyebrow="Project questions"
        title="Ask questions about the project."
        body="Ask in plain language. The agent fetches only the context the question needs (the relevant files, symbols or recent activity) and answers that question, citing where it found the answer."
        visual={
          <div className="space-y-3 rounded-lg border border-border bg-surface p-4">
            <p className="ml-auto w-fit max-w-[85%] rounded-lg rounded-br-sm bg-accent-muted px-3 py-2 text-sm text-fg">
              How does authentication work?
            </p>
            <div className="max-w-[92%] rounded-lg rounded-bl-sm border border-border bg-surface-sunken px-3 py-2.5 text-sm leading-relaxed text-fg">
              <p className="mb-1.5 flex items-center gap-1.5 text-[10px] tracking-[0.14em] text-fg-subtle uppercase">
                <Sparkles aria-hidden className="size-3 text-accent" /> From api/auth.py,
                services/auth.py
              </p>
              POST /login calls <code className="font-mono">AuthService.authenticate()</code>, which
              verifies the password hash on <code className="font-mono">User</code> and starts a
              server-side session (services/auth.py:18).
            </div>
          </div>
        }
      />
      <Story
        eyebrow="Context-aware fixes"
        title="Fix with context."
        body="A fix starts from the problem, pulls in the files it depends on, explains the cause, and arrives as a diff. You review it, then apply or reject. A stale proposal is reported, never forced in."
        visual={
          <div className="space-y-2 rounded-lg border border-border bg-surface p-4 text-[13px]">
            <p className="flex items-center gap-2 text-fg">
              <CircleX aria-label="Error" className="size-4 text-danger" /> Undefined name
              <code className="font-mono">session_store</code>
            </p>
            <p className="pl-6 font-mono text-[11.5px] text-fg-muted">→ services.py · models.py</p>
            <p className="pl-6 text-fg-muted">
              → “Load the user through get_session() from services.py.”
            </p>
            <div className="pl-6">
              <MiniDiff
                file="auth.py"
                removed={['user = session_store.get(claims["sub"])']}
                added={['user = get_session().get(User, claims["sub"])']}
              />
            </div>
            <div className="flex gap-2 pt-1 pl-6" aria-hidden>
              <span className="rounded bg-accent px-2.5 py-1 text-xs font-medium text-on-accent">
                Apply
              </span>
              <span className="rounded border border-border px-2.5 py-1 text-xs text-fg">
                Reject
              </span>
              <span className="ml-auto self-center text-[11px] text-fg-subtle">
                Nothing applied yet
              </span>
            </div>
          </div>
        }
      />
      <Story
        flip
        eyebrow="Project-aware search"
        title="Search beyond file names."
        body="Search finds functions, classes, imports and identifiers across the project, and ranks results that are related to the file you are working on higher. Each result says why it matched."
        visual={
          <div className="overflow-hidden rounded-lg border border-border bg-surface">
            <p className="flex items-center gap-2 border-b border-border bg-surface-sunken px-3 py-2 font-mono text-[13px] text-fg">
              <Search aria-hidden className="size-4 text-fg-subtle" /> authenticate
            </p>
            <ul className="divide-y divide-border text-[12.5px]">
              {[
                ["function", "authenticate_user", "auth.py:6"],
                ["class", "AuthService", "services/auth.py:9"],
                ["import", "from services import verify_token", "auth.py:3"],
                ["identifier", "authenticate", "api/auth.py:14"],
                ["related file", "tests/test_auth.py", "imports auth.py"],
              ].map(([kind, name, where]) => (
                <li
                  key={name}
                  className="grid grid-cols-[5.5rem_1fr_auto] items-center gap-3 px-3 py-2"
                >
                  <span className="text-[10px] tracking-wide text-fg-subtle uppercase">{kind}</span>
                  <span className="truncate font-mono text-fg">{name}</span>
                  <span className="font-mono text-[11px] text-fg-subtle">{where}</span>
                </li>
              ))}
            </ul>
          </div>
        }
      />
    </div>
  );
}

// --- 8. How it works ------------------------------------------------------------------------------

const STEPS = [
  ["Open project", "Create a project, open one you already have, or upload a folder."],
  ["Write code", "Edit in Monaco, the editor behind VS Code, with your language's highlighting."],
  ["Detect problems", "Diagnostics appear as you type, in the editor and the Problems panel."],
  ["Understand context", "CodeWalk knows the project's files, symbols and imports."],
  ["Ask AI", "Explain an error, ask about the project, or request a fix."],
  ["Review", "Changes arrive as diffs. You apply or reject them."],
];

export function HowItWorks() {
  return (
    <section id="how-it-works" aria-labelledby="how-title" className="py-24 sm:py-32">
      <div
        className={`${container} grid grid-cols-1 gap-14 lg:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)]`}
      >
        <div className="lg:sticky lg:top-24 lg:self-start">
          <SectionHeading
            id="how-title"
            eyebrow="How it works"
            title="Six steps from an open project to a reviewed change."
          />
          <p
            className={`${styles.reveal} mt-8 border-l-2 border-accent pl-4 text-lg font-medium text-fg`}
          >
            AI assists. The developer stays in control.
          </p>
        </div>
        <ol className="relative space-y-4 before:absolute before:top-2 before:bottom-2 before:left-[15px] before:w-px before:bg-border">
          {STEPS.map(([title, body], i) => (
            <li key={title} className="relative grid grid-cols-[2rem_1fr] gap-4">
              <span
                aria-hidden
                className={`relative z-10 mt-4 size-[11px] justify-self-center rounded-full border border-border-strong bg-surface-raised ${styles.dotOnView}`}
              />
              <div
                className={`rounded-lg border border-border bg-surface px-5 py-4 text-fg-muted ${styles.stepOnView}`}
              >
                <p className="flex items-baseline gap-3">
                  <span className="font-mono text-xs text-accent-text">
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <span className="text-[15px] font-semibold tracking-wide text-fg uppercase">
                    {title}
                  </span>
                </p>
                <p className="mt-1 pl-8 text-[15px] leading-relaxed">{body}</p>
              </div>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

// --- 9. Project intelligence ---------------------------------------------------------------------

export function ProjectIntelligence() {
  return (
    <section
      aria-labelledby="graph-title"
      className="border-y border-border bg-surface-sunken py-24 sm:py-32"
    >
      <div className={container}>
        <SectionHeading
          id="graph-title"
          eyebrow="Project intelligence"
          title="The project as a set of relationships."
          intro="CodeWalk resolves imports between files, finds related tests and HTTP routes, and shows what could break when you change something. Select a file to see how it connects."
        />
        <div className={`${styles.reveal} mt-12`}>
          <ProjectGraph />
        </div>
      </div>
    </section>
  );
}

// --- 10. AI + human control -----------------------------------------------------------------------

export function HumanControl() {
  const column = (title: string, items: string[], accent: boolean) => (
    <div
      className={`${styles.reveal} rounded-lg border p-6 ${accent ? "border-accent/60 bg-surface" : "border-border bg-surface"}`}
    >
      <p
        className={`text-[11px] font-semibold tracking-[0.2em] uppercase ${accent ? "text-accent-text" : "text-fg-subtle"}`}
      >
        {title}
      </p>
      <ul className="mt-4 space-y-2.5">
        {items.map((item) => (
          <li
            key={item}
            className="flex items-center gap-2.5 text-lg font-medium tracking-tight text-fg"
          >
            <Check aria-hidden className={`size-4 ${accent ? "text-accent" : "text-fg-subtle"}`} />
            {item}
          </li>
        ))}
      </ul>
    </div>
  );
  const flow = ["AI", "Suggestion", "Diff", "Developer", "Apply / Reject"];
  return (
    <section id="ai" aria-labelledby="ai-title" className="py-24 sm:py-32">
      <div className={container}>
        <SectionHeading
          id="ai-title"
          align="center"
          eyebrow="AI + human control"
          title={
            <>
              AI can suggest the change.
              <br />
              <span className="text-accent">You decide what enters your code.</span>
            </>
          }
          intro="CodeWalk is not an autonomous coder. The agent reads your project through read-only tools and can only store proposals; applying one always takes your explicit approval."
        />
        <div className="mt-14 grid grid-cols-1 items-stretch gap-4 lg:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)]">
          {column("AI", ["Understands", "Retrieves", "Explains", "Suggests"], false)}
          <ol
            aria-label="Review flow"
            className={`${styles.reveal} flex flex-col items-center justify-center gap-1.5 px-2 py-4`}
          >
            <li className="mb-1 rounded-full border border-accent bg-accent-muted px-3 py-0.5 text-[10px] font-semibold tracking-[0.2em] text-fg uppercase">
              Review
            </li>
            {flow.map((step, i) => (
              <li key={step} className="flex flex-col items-center gap-1.5">
                <span className="rounded border border-border bg-surface px-3 py-1 font-mono text-[12px] text-fg">
                  {step}
                </span>
                {i < flow.length - 1 && (
                  <ArrowDown aria-hidden className="size-3.5 text-fg-subtle" />
                )}
              </li>
            ))}
          </ol>
          {column("Developer", ["Reviews", "Accepts", "Rejects", "Edits", "Decides"], true)}
        </div>
      </div>
    </section>
  );
}

// --- 11. Ask your project -----------------------------------------------------------------------

export function AskSection() {
  return (
    <section
      aria-labelledby="ask-title"
      className="border-t border-border bg-surface-sunken py-24 sm:py-32"
    >
      <div className={container}>
        <SectionHeading
          id="ask-title"
          align="center"
          eyebrow="Ask your project"
          title="Ask your project."
          intro="Retrieve only the context needed to answer the question."
        />
        <div className={`${styles.reveal} mt-12`}>
          <AskProject />
        </div>
      </div>
    </section>
  );
}

// --- 12. Workspace showcase -------------------------------------------------------------------------

const SERVICE_CODE = [
  "from models import Invoice, User",
  "from services import get_session",
  "",
  "",
  "def total_due(user: User) -> float:",
  '    """Sum of open invoices for a user, in the account currency."""',
  "    invoices = get_session().query(Invoice).filter_by(user_id=user.id)",
  "    total = 0",
  "    for invoice in invoices:",
  '        if invoice.status != "paid":',
  "            total += invoice.amount",
  "    return round(total, 2)",
  "",
  "",
  "def apply_discount(total: float, percent: float) -> float:",
  "    return total - percent",
];

export function WorkspaceShowcase() {
  return (
    <section aria-labelledby="showcase-title" className="py-24 sm:py-32">
      <div className="mx-auto max-w-[96rem] px-4 sm:px-6">
        <div className="mb-10 text-center">
          <Eyebrow>The CodeWalk workspace</Eyebrow>
          <h2
            id="showcase-title"
            className="mt-3 text-3xl font-semibold tracking-[-0.025em] text-fg sm:text-[2.6rem]"
          >
            One workspace for code, context, diagnostics, and AI.
          </h2>
        </div>
        <MockWindow
          project="Payments API"
          file="services/billing.py"
          label="The CodeWalk workspace: file list, editor, Problems panel, and the AI agent answering a question about the open file"
          className={styles.reveal}
        >
          <div className="grid grid-cols-1 md:grid-cols-[12rem_minmax(0,1fr)] xl:grid-cols-[13rem_minmax(0,1fr)_19rem]">
            <div className="hidden border-r border-border md:block">
              <FileList
                title="Code files"
                files={[
                  "api/billing.py",
                  "models.py",
                  "services/billing.py",
                  "services/__init__.py",
                  "tests/test_billing.py",
                  "README.md",
                ]}
                active="services/billing.py"
                related={["models.py", "tests/test_billing.py"]}
              />
            </div>
            <div className="min-w-0">
              <div className="flex h-8 items-end gap-px border-b border-border bg-surface-sunken pl-2">
                <span className="flex h-7 items-center gap-1.5 rounded-t border border-b-0 border-border bg-surface px-3 font-mono text-[11px] text-fg">
                  <FileCode2 aria-hidden className="size-3 text-accent" /> billing.py
                </span>
                <span className="flex h-7 items-center px-3 font-mono text-[11px] text-fg-subtle">
                  models.py
                </span>
              </div>
              <div className={`overflow-x-auto py-2 ${styles.mockScroll}`}>
                <CodeLines lines={SERVICE_CODE} current={16} />
              </div>
              <ProblemsPanel
                problems={[
                  {
                    severity: "info",
                    message: "No problems found by static analysis",
                    source: "python",
                    location: "",
                  },
                ]}
              />
            </div>
            <AiPanel
              context={["services/billing.py:15", "api/billing.py", "tests/test_billing.py"]}
              className="border-t border-border md:col-span-2 xl:col-span-1 xl:border-t-0 xl:border-l"
            >
              <p className="rounded bg-accent-muted px-2 py-1.5 text-fg">
                Is apply_discount correct?
              </p>
              <p className="text-fg">
                Static analysis cannot see this one: it subtracts the percentage as an amount:{" "}
                <code className="font-mono">total - percent</code>. With total 200 and 10 percent it
                returns 190, not 180. api/billing.py:31 and tests/test_billing.py:12 reference it.
              </p>
              <MiniDiff
                file="services/billing.py"
                removed={["return total - percent"]}
                added={["return total * (1 - percent / 100)"]}
              />
              <p className="flex items-center gap-1.5 text-[11px] text-fg-subtle">
                <ShieldCheck aria-hidden className="size-3.5" /> Proposal · review before applying
              </p>
            </AiPanel>
          </div>
        </MockWindow>
      </div>
    </section>
  );
}

// --- 13. Architecture --------------------------------------------------------------------------------

const LAYERS: { layer: string; detail: string; tech: string[] }[] = [
  { layer: "User", detail: "In the browser", tech: ["Any modern browser"] },
  {
    layer: "CodeWalk workspace",
    detail: "Editor, explorer, panels, themes",
    tech: ["Next.js 16", "React 19", "TypeScript", "Tailwind CSS 4", "Monaco Editor"],
  },
  {
    layer: "API",
    detail: "Auth, projects, files, ownership",
    tech: ["FastAPI", "Python 3.12", "Pydantic"],
  },
  {
    layer: "Code analysis + project intelligence",
    detail: "Diagnostics, symbols, imports, search",
    tech: ["ruff", "TypeScript compiler", "tree-sitter", "sqlglot", "Deterministic search"],
  },
  {
    layer: "AI / RAG / agent workflows",
    detail: "Explanations, fixes, agent, retrieval",
    tech: ["Anthropic", "OpenAI-compatible", "Voyage voyage-code-4", "Hybrid RRF search"],
  },
  {
    layer: "PostgreSQL",
    detail: "Projects, files, versions, embeddings",
    tech: ["PostgreSQL 17", "pgvector", "SQLAlchemy 2", "Alembic"],
  },
  {
    layer: "Docker",
    detail: "Development and production stacks",
    tech: ["Docker Compose", "Nginx"],
  },
];

export function Architecture() {
  return (
    <section
      aria-labelledby="arch-title"
      className="border-y border-border bg-surface-sunken py-24 sm:py-32"
    >
      <div
        className={`${container} grid grid-cols-1 gap-14 lg:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)]`}
      >
        <SectionHeading
          id="arch-title"
          eyebrow="Technology"
          title="A layered architecture, from the browser to the database."
          intro="AI providers are optional and server-side only: without them, the editor, diagnostics, search, and project intelligence keep working."
        />
        <ol className="space-y-2">
          {LAYERS.map((l, i) => (
            <li key={l.layer} className={styles.reveal}>
              <div className="grid gap-3 rounded-lg border border-border bg-surface px-4 py-3 sm:grid-cols-[13rem_1fr] sm:items-center">
                <div>
                  <p className="text-[13px] font-semibold tracking-wide text-fg uppercase">
                    {l.layer}
                  </p>
                  <p className="text-xs text-fg-subtle">{l.detail}</p>
                </div>
                <ul className="flex flex-wrap gap-1.5">
                  {l.tech.map((t) => (
                    <li
                      key={t}
                      className="rounded border border-border bg-surface-sunken px-2 py-0.5 font-mono text-[11.5px] text-fg-muted"
                    >
                      {t}
                    </li>
                  ))}
                </ul>
              </div>
              {i < LAYERS.length - 1 && (
                <ArrowDown aria-hidden className="mx-auto my-1 size-3.5 text-fg-subtle" />
              )}
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

// --- 14. FAQ ----------------------------------------------------------------------------------------

const FAQS: [string, string][] = [
  [
    "What is CodeWalk Agent?",
    "An AI-assisted coding environment in the browser: a Monaco editor with real-time diagnostics, project intelligence and search, AI explanations and fix suggestions, and an agent whose changes you review before anything is applied.",
  ],
  [
    "How is it different from a normal editor?",
    "It understands the project, not only the open file: symbols, imports and how files depend on each other, related tests and routes. Search, diagnostics and AI answers use that context.",
  ],
  [
    "Can it understand a complete project?",
    "It indexes the files of a project you create, upload or link, resolves imports between them, and retrieves the parts a question needs. It is static analysis: there is no call graph or type checking across the whole codebase, and the analysis says so.",
  ],
  [
    "How does diagnostics work?",
    "The backend analysis engine parses the open file as you type and reports syntax errors, undefined names and lint findings in the editor and the Problems panel. Your code is analyzed, never executed.",
  ],
  [
    "Can AI explain errors?",
    "Yes, when an AI provider is configured on the server: it explains a diagnostic using the file and its context, and can suggest a fix you review as a diff.",
  ],
  [
    "Does AI automatically modify my code?",
    "No. The agent can only store proposals. Each one is shown as a diff and applied only when you approve it, and only if the file has not changed since the proposal was made.",
  ],
  [
    "How does RAG help?",
    "Code is split into chunks and embedded (Voyage voyage-code-4, stored with pgvector). Semantic and hybrid search then retrieve the few snippets relevant to a question, so the AI sees what it needs instead of the whole project.",
  ],
  [
    "What are AI agents used for?",
    "Bounded workflows: asking about code, fixing a problem, reviewing a file, generating tests or documentation, multi-file refactors, impact analysis and architecture questions. The agent uses read-only tools within step and token limits.",
  ],
];

export function Faq() {
  return (
    <section id="faq" aria-labelledby="faq-title" className="py-24 sm:py-32">
      <div
        className={`${container} grid grid-cols-1 gap-12 lg:grid-cols-[minmax(0,0.7fr)_minmax(0,1.3fr)]`}
      >
        <SectionHeading id="faq-title" eyebrow="FAQ" title="Questions, answered precisely." />
        <div className="divide-y divide-border border-y border-border">
          {FAQS.map(([question, answer], i) => (
            <details key={question} name="faq" open={i === 0} className="group">
              <summary className="flex cursor-pointer list-none items-center gap-4 py-5 text-left text-[17px] font-medium text-fg [&::-webkit-details-marker]:hidden">
                <span className="flex-1">{question}</span>
                <ChevronDown
                  aria-hidden
                  className="size-4 shrink-0 text-fg-subtle transition-transform duration-200 group-open:rotate-180"
                />
              </summary>
              <p className="max-w-2xl pb-6 text-[15px] leading-relaxed text-fg-muted">{answer}</p>
            </details>
          ))}
        </div>
      </div>
    </section>
  );
}

// --- 15–16. Final CTA and footer ------------------------------------------------------------------

export function FinalCta() {
  const nodes: [number, number][] = [
    [8, 30],
    [20, 70],
    [34, 22],
    [48, 80],
    [62, 28],
    [76, 74],
    [90, 34],
    [96, 82],
    [4, 86],
  ];
  return (
    <section
      aria-labelledby="cta-title"
      className="relative overflow-hidden border-t border-border bg-surface-sunken"
    >
      <svg
        aria-hidden
        viewBox="0 0 100 100"
        preserveAspectRatio="none"
        className="pointer-events-none absolute inset-0 size-full opacity-60"
      >
        {nodes.slice(0, -1).map(([x, y], i) => (
          <line
            key={`l${i}`}
            x1={x}
            y1={y}
            x2={nodes[i + 1][0]}
            y2={nodes[i + 1][1]}
            stroke="var(--color-border-strong)"
            vectorEffect="non-scaling-stroke"
            pathLength={1}
            className={`${styles.line} ${styles.drawOnView}`}
          />
        ))}
      </svg>
      <div className="pointer-events-none absolute inset-0" aria-hidden>
        {nodes.map(([x, y], i) => (
          <span
            key={`n${i}`}
            className={`absolute size-2 -translate-x-1/2 -translate-y-1/2 rounded-full ${i % 3 === 0 ? "bg-accent" : "bg-border-strong"}`}
            style={{ left: `${x}%`, top: `${y}%` }}
          />
        ))}
      </div>
      <div className={`${container} relative py-28 text-center sm:py-36`}>
        <h2
          id="cta-title"
          className={`${styles.reveal} text-[clamp(2.4rem,6.5vw,4.75rem)] leading-[1.02] font-semibold tracking-[-0.04em] text-fg`}
        >
          Stop Debugging <span className="text-accent">Alone.</span>
        </h2>
        <p
          className={`${styles.reveal} mx-auto mt-6 max-w-xl text-lg leading-relaxed text-fg-muted`}
        >
          Understand your code, understand your project, and build with AI that works with you.
        </p>
        <div className={`${styles.reveal} mt-10 flex flex-col justify-center gap-3 sm:flex-row`}>
          <Link href="/app/coding" className={primaryCta}>
            Open CodeWalk Agent
            <ArrowRight
              aria-hidden
              className="size-4 transition-transform group-hover:translate-x-0.5"
            />
          </Link>
          <Link href="/app/projects" className={secondaryCta}>
            Explore the Workspace
          </Link>
        </div>
      </div>
    </section>
  );
}

export function Footer() {
  return (
    <footer className="border-t border-border bg-app">
      <div
        className={`${container} grid grid-cols-1 gap-8 py-12 md:grid-cols-[minmax(0,1fr)_auto] md:items-start`}
      >
        <div className="max-w-sm">
          <p className="flex items-center gap-2 text-sm font-semibold tracking-tight text-fg">
            <LogoMark className="size-5" /> CodeWalk Agent
          </p>
          <p className="mt-3 text-sm leading-relaxed text-fg-muted">
            An AI-powered coding environment that understands your codebase.
          </p>
        </div>
        <nav aria-label="Footer">
          <ul className="flex flex-wrap gap-x-6 gap-y-2 text-sm">
            {LANDING_SECTIONS.map((s) => (
              <li key={s.id}>
                <a href={`#${s.id}`} className="text-fg-muted hover:text-fg">
                  {s.label}
                </a>
              </li>
            ))}
            <li>
              <Link href="/app/coding" className="text-fg-muted hover:text-fg">
                Workspace
              </Link>
            </li>
            <li>
              <Link href="/login" className="text-fg-muted hover:text-fg">
                Sign In
              </Link>
            </li>
          </ul>
        </nav>
      </div>
      <div
        className={`${container} flex flex-wrap items-center justify-between gap-2 border-t border-border py-5 text-xs text-fg-subtle`}
      >
        <p>© {new Date().getFullYear()} CodeWalk Agent</p>
        <p className="flex items-center gap-1.5">
          <ShieldCheck aria-hidden className="size-3.5" /> Code is analyzed, never executed.
        </p>
      </div>
    </footer>
  );
}
