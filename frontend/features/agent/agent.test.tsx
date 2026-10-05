// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect, useRef, type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { WorkspaceProviders } from "@/features/workspace/workspace";
import { useWorkspace } from "@/features/workspace/workspace-context";
import {
  apiError,
  fakeBackend,
  json,
  makeProject,
  page,
  requestsOf,
  type Route,
} from "@/testing/fake-api";
import type { Diagnostic } from "@/types/diagnostics";

import { useAgent } from "./agent-context";
import { AgentPanel } from "./agent-panel";
import { AgentReview } from "./agent-review";

// The diff view is Monaco's DiffEditor, which needs a real browser; render its inputs instead.
vi.mock("next/dynamic", () => ({
  default: () =>
    function DiffStub(props: { original?: string; modified?: string }) {
      return (
        <pre data-testid="diff">
          {props.original}
          {"=>"}
          {props.modified}
        </pre>
      );
    },
}));

const PATH = "shop/cart.py";
const CODE =
  "def cart_total(items):\n    for item in items:\n        total += item.price\n    return total\n";
const FIXED =
  "def cart_total(items):\n    total = 0\n    for item in items:\n        total += item.price\n    return total\n";

const FILE = {
  id: "f1",
  project_id: "p1",
  path: PATH,
  name: "cart.py",
  language: "python",
  size: CODE.length,
  line_count: 4,
  content_hash: "h",
  has_content: true,
  created_at: "2026-10-01T00:00:00Z",
  updated_at: "2026-10-01T00:00:00Z",
};

const DIAGNOSTIC: Diagnostic = {
  id: "d1",
  severity: "error",
  category: "lint",
  message: "Undefined name `total`",
  file: PATH,
  line: 3,
  column: 9,
  endLine: 3,
  endColumn: 14,
  source: "ruff",
  code: "F821",
  fixable: false,
  unnecessary: false,
};

const ACTION = {
  id: "a1",
  run_id: "r1",
  kind: "code_change",
  status: "pending",
  file_path: PATH,
  summary: "Initialise total before the loop",
  explanation: "total is used before assignment.",
  changes: [
    {
      file_path: PATH,
      start_line: 2,
      start_column: 1,
      end_line: 3,
      end_column: 1,
      original_text: "    for item in items:\n",
      replacement_text: "    total = 0\n    for item in items:\n",
    },
  ],
  diff: "--- a/shop/cart.py\n+++ b/shop/cart.py\n@@ -1,4 +1,5 @@\n def cart_total(items):\n+    total = 0\n",
  base_content_hash: "h",
  validation: "valid",
  created_at: "2026-10-04T10:00:00Z",
  decided_at: null,
  result: {},
};

const event = (type: string, message: string, tool: string | null = null) => ({
  type,
  message,
  tool,
  at: "2026-10-04T10:00:00Z",
  data: {},
});

const RUN = {
  id: "r1",
  project_id: "p1",
  status: "completed",
  message: "Fix the undefined total",
  file_path: PATH,
  answer: "`total` is never initialised (shop/cart.py line 3). I proposed a fix for your review.",
  provider: "anthropic",
  model: "claude-opus-5-5",
  error: null,
  events: [
    event("started", "Agent started"),
    event("planning", "Reading the file"),
    event("tool_started", "Reading a file…", "get_file_content"),
    event("tool_completed", "Read shop/cart.py lines 1-4", "get_file_content"),
    event("tool_denied", "Not allowed: There is no tool named 'execute_code'.", "execute_code"),
    event("tool_started", "Preparing a proposed change…", "propose_fix"),
    event("tool_completed", "Proposed a change to shop/cart.py", "propose_fix"),
    event("action_proposed", "Proposed a change to shop/cart.py"),
    event("response", "Prepared a response"),
    event("completed", "Completed"),
  ],
  tool_calls: [
    {
      index: 1,
      tool: "get_file_content",
      permission: "read_only",
      arguments: { file_path: PATH },
      status: "ok",
      summary: "Read shop/cart.py lines 1-4",
      duration_ms: 3,
    },
  ],
  actions: [ACTION],
  warnings: [],
  duration_ms: 4200,
  created_at: "2026-10-04T10:00:00Z",
  completed_at: "2026-10-04T10:00:04Z",
};

const STATUS = (available: boolean) =>
  json({
    available,
    detail: available
      ? null
      : "AI assistance is turned off (set CODEWALK_AI_ENABLED=true to enable it).",
    tools: [],
    max_steps: 8,
    max_actions: 3,
  });

const projectRoutes: Route[] = [
  ["GET", /^\/projects\/p1\/files$/, () => json({ ...page([FILE]), limit: 5000 })],
  ["GET", /^\/projects\/p1\/files\/f1$/, () => json({ ...FILE, content: CODE })],
];

/** Opens server project p1 with shop/cart.py and one diagnostic, then renders children. */
function Harness({ children }: { children: ReactNode }) {
  const { state, actions } = useWorkspace();
  const started = useRef(false);
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    void (async () => {
      await actions.openServerProject(makeProject());
      await actions.openFile(PATH);
      actions.replaceDiagnostics("analysis", PATH, [DIAGNOSTIC]);
    })();
  }, [actions]);
  const buffer = state.buffers[PATH];
  return (
    <>
      <div data-testid="buffer">{buffer?.content}</div>
      <div data-testid="dirty">
        {buffer && buffer.content !== buffer.savedContent ? "dirty" : "clean"}
      </div>
      <button type="button" onClick={() => actions.editFile(PATH, CODE + "# edited\n")}>
        edit-file
      </button>
      {state.project && buffer?.status === "ready" ? children : null}
    </>
  );
}

function renderAgent(routes: Route[], fetchImpl?: typeof fetch) {
  const fetchMock = fetchImpl ?? fakeBackend([...projectRoutes, ...routes]);
  vi.stubGlobal("fetch", fetchMock);
  render(
    <WorkspaceProviders>
      <Harness>
        <AgentPanel />
        <AgentReview path={PATH} />
      </Harness>
    </WorkspaceProviders>,
  );
  return fetchMock as ReturnType<typeof fakeBackend>;
}

async function ask(text: string) {
  await userEvent.type(await screen.findByLabelText("Ask about your project"), text);
  await userEvent.click(screen.getByRole("button", { name: "Ask agent" }));
}

afterEach(() => vi.unstubAllGlobals());

describe("Agent panel", () => {
  it("explains why the agent is unavailable and sends nothing", async () => {
    const fetchMock = renderAgent([["GET", /^\/agent\/status$/, () => STATUS(false)]]);
    expect(
      await screen.findByText(/Agent unavailable: AI assistance is turned off/),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Ask about your project")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Ask agent" })).toBeDisabled();
    expect(requestsOf(fetchMock).some((r) => r.path === "/agent/run")).toBe(false);
  });

  it("sends the open file and its problems, then shows activity, answer, and the proposal", async () => {
    const fetchMock = renderAgent([
      ["GET", /^\/agent\/status$/, () => STATUS(true)],
      ["POST", /^\/agent\/run$/, () => json(RUN)],
    ]);
    await ask("Fix the undefined total");

    expect(await screen.findByText(/is never initialised/)).toBeInTheDocument();
    const sent = requestsOf(fetchMock).find((r) => r.path === "/agent/run")!;
    expect(sent.body).toMatchObject({
      project_id: "p1",
      message: "Fix the undefined total",
      file_path: PATH,
      code: CODE,
      diagnostics: [{ id: "d1", message: "Undefined name `total`", line: 3 }],
    });
    expect(sent.body.selection).toBeUndefined();

    const activity = screen.getByRole("list", { name: "Agent activity" });
    expect(within(activity).getByText("Read shop/cart.py lines 1-4")).toBeInTheDocument();
    expect(within(activity).getByText(/Not allowed: There is no tool named/)).toBeInTheDocument();
    expect(screen.queryByText("Agent started")).not.toBeInTheDocument();

    const card = screen.getByRole("listitem", { name: `Proposed change to ${PATH}` });
    expect(within(card).getByText("Initialise total before the loop")).toBeInTheDocument();
    expect(within(card).getByText("waiting for your review")).toBeInTheDocument();
    expect(screen.getByTestId("buffer").textContent).toBe(CODE); // nothing applied
  });

  it("reviews the diff and applies only on explicit approval", async () => {
    const fetchMock = renderAgent([
      ["GET", /^\/agent\/status$/, () => STATUS(true)],
      ["POST", /^\/agent\/run$/, () => json(RUN)],
      [
        "POST",
        /^\/agent\/actions\/a1\/approve$/,
        () =>
          json({
            action: { ...ACTION, status: "applied", decided_at: "2026-10-04T10:01:00Z" },
            file: { file_id: "f1", path: PATH, content: FIXED, content_hash: "h2", version: 2 },
            diagnostics: [],
          }),
      ],
    ]);
    await ask("Fix it");
    await userEvent.click(await screen.findByRole("button", { name: "Review diff" }));
    const review = await screen.findByRole("region", { name: "Review proposed change" });
    expect(within(review).getByTestId("diff").textContent).toBe(`${CODE}=>${FIXED}`);
    expect(screen.getByTestId("buffer").textContent).toBe(CODE);
    expect(requestsOf(fetchMock).some((r) => r.path.includes("/approve"))).toBe(false);

    await userEvent.click(within(review).getByRole("button", { name: "Apply" }));
    await waitFor(() => expect(screen.getByTestId("buffer").textContent).toBe(FIXED));
    expect(screen.getByTestId("dirty").textContent).toBe("clean"); // saved by the backend
    expect(
      screen.queryByRole("region", { name: "Review proposed change" }),
    ).not.toBeInTheDocument();
    const card = screen.getByRole("listitem", { name: `Proposed change to ${PATH}` });
    expect(within(card).getByText("applied")).toBeInTheDocument();
    expect(within(card).queryByRole("button", { name: "Apply" })).not.toBeInTheDocument();
  });

  it("rejects without touching the file", async () => {
    const fetchMock = renderAgent([
      ["GET", /^\/agent\/status$/, () => STATUS(true)],
      ["POST", /^\/agent\/run$/, () => json(RUN)],
      [
        "POST",
        /^\/agent\/actions\/a1\/reject$/,
        () => json({ action: { ...ACTION, status: "rejected" }, file: null, diagnostics: [] }),
      ],
    ]);
    await ask("Fix it");
    await userEvent.click(await screen.findByRole("button", { name: "Reject" }));
    const card = await screen.findByRole("listitem", { name: `Proposed change to ${PATH}` });
    await waitFor(() => expect(within(card).getByText("rejected")).toBeInTheDocument());
    expect(screen.getByTestId("buffer").textContent).toBe(CODE);
    expect(requestsOf(fetchMock).some((r) => r.path.includes("/approve"))).toBe(false);
  });

  it("refuses to apply over unsaved edits and reports stale proposals", async () => {
    renderAgent([
      ["GET", /^\/agent\/status$/, () => STATUS(true)],
      ["POST", /^\/agent\/run$/, () => json(RUN)],
      [
        "POST",
        /^\/agent\/actions\/a1\/approve$/,
        () => apiError(409, "stale_action", "The file changed after this change was proposed."),
      ],
    ]);
    await ask("Fix it");
    const card = await screen.findByRole("listitem", { name: `Proposed change to ${PATH}` });

    await userEvent.click(screen.getByRole("button", { name: "edit-file" }));
    expect(within(card).getByRole("button", { name: "Apply" })).toBeDisabled();
    expect(within(card).getByText(/Save or undo your unsaved edits/)).toBeInTheDocument();
  });

  it("shows a stale proposal from the server instead of applying it", async () => {
    renderAgent([
      ["GET", /^\/agent\/status$/, () => STATUS(true)],
      ["POST", /^\/agent\/run$/, () => json(RUN)],
      [
        "POST",
        /^\/agent\/actions\/a1\/approve$/,
        () => apiError(409, "stale_action", "The file changed after this change was proposed."),
      ],
    ]);
    await ask("Fix it");
    await userEvent.click(await screen.findByRole("button", { name: "Apply" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The file changed after this change was proposed.",
    );
    const card = screen.getByRole("listitem", { name: `Proposed change to ${PATH}` });
    expect(within(card).getByText("stale")).toBeInTheDocument();
    expect(screen.getByTestId("buffer").textContent).toBe(CODE);
  });

  it.each([
    [
      "rate limit",
      () =>
        apiError(429, "too_many_agent_runs", "Too many agent requests. Try again in 60 seconds."),
      /Too many agent requests/,
    ],
    [
      "provider off",
      () => apiError(503, "ai_disabled", "AI assistance is turned off on this server."),
      /turned off/,
    ],
    [
      "no access",
      () => apiError(404, "project_not_found", "Project not found."),
      /Project not found/,
    ],
    [
      "failed run",
      () =>
        json({
          ...RUN,
          status: "failed",
          answer: null,
          actions: [],
          error: { code: "ai_timeout", message: "The AI provider did not answer in time." },
        }),
      /did not answer in time/,
    ],
    [
      "limit",
      () =>
        json({
          ...RUN,
          status: "limit_reached",
          answer: null,
          actions: [],
          warnings: ["The agent stopped at the step limit before answering."],
        }),
      /stopped at a limit/,
    ],
    [
      "backend unreachable",
      () => {
        throw new TypeError("Failed to fetch");
      },
      /backend is not reachable/,
    ],
    [
      "malformed response",
      () => json({ unexpected: "shape" }),
      /did not match the expected format/,
    ],
    [
      "server error without details",
      () => new Response("<html>Traceback (most recent call last): ...</html>", { status: 500 }),
      /not valid JSON|HTTP 500/,
    ],
    [
      "session expired",
      () => apiError(401, "not_authenticated", "Sign in to continue."),
      /Sign in to continue/,
    ],
  ])("shows %s states", async (_name, respond, text) => {
    renderAgent([
      ["GET", /^\/agent\/status$/, () => STATUS(true)],
      ["POST", /^\/agent\/run$/, respond],
    ]);
    await ask("Why?");
    expect(await screen.findByRole("alert")).toHaveTextContent(text);
    expect(screen.queryByText(/Traceback/)).not.toBeInTheDocument(); // never a raw stack trace
    expect(screen.getByRole("button", { name: "Ask agent" })).toBeEnabled(); // never stuck loading
  });

  it("can cancel a running request", async () => {
    const routes = fakeBackend([
      ...projectRoutes,
      ["GET", /^\/agent\/status$/, () => STATUS(true)],
    ]);
    const fetchImpl = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).endsWith("/agent/run")) {
        return new Promise<Response>((_, reject) =>
          init?.signal?.addEventListener("abort", () =>
            reject(new DOMException("Aborted", "AbortError")),
          ),
        );
      }
      return routes(input, init);
    }) as unknown as typeof fetch;
    renderAgent([], fetchImpl);
    await ask("Long question");
    expect(await screen.findByRole("status")).toHaveTextContent(/Working on/);
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/Cancelled/);
    expect(screen.getByRole("button", { name: "Ask agent" })).toBeEnabled();
  });
});

describe("Agent request races", () => {
  const OLD = "OLD ANSWER from the first run";
  const NEW = "NEW ANSWER from the second run";

  /**
   * Run 1 answers only when the test says so (a slow server) and, like a real fetch, rejects
   * when aborted; `abortDelayMs` delays that rejection to model it settling after newer work
   * has started. Run 2 answers at once. Nothing depends on how fast the test runs.
   */
  function slowFirstRun(abortDelayMs = 0) {
    const routes = fakeBackend([
      ...projectRoutes,
      ["GET", /^\/agent\/status$/, () => STATUS(true)],
    ]);
    let calls = 0;
    let answerFirst: () => void = () => {};
    const fetchImpl = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (!String(input).endsWith("/agent/run")) return routes(input, init);
      calls += 1;
      if (calls > 1) return Promise.resolve(json({ ...RUN, answer: NEW, actions: [] }));
      return new Promise<Response>((resolve, reject) => {
        answerFirst = () => resolve(json({ ...RUN, answer: OLD, actions: [] }));
        init?.signal?.addEventListener("abort", () =>
          setTimeout(() => reject(new DOMException("Aborted", "AbortError")), abortDelayMs),
        );
      });
    }) as unknown as typeof fetch;
    return { fetchImpl, answerFirst: () => answerFirst() };
  }

  it("a cancelled run frees the panel and its late answer never appears", async () => {
    const { fetchImpl, answerFirst } = slowFirstRun();
    renderAgent([], fetchImpl);
    await ask("First question");
    await userEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/Cancelled/);
    await userEvent.clear(screen.getByLabelText("Ask about your project"));
    await ask("Second question");
    expect(await screen.findByText(NEW)).toBeInTheDocument();
    answerFirst(); // the server's answer to the cancelled run arrives late
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(screen.queryByText(OLD)).not.toBeInTheDocument();
    expect(screen.queryByText(/Cancelled/)).not.toBeInTheDocument();
    expect(screen.getByText(NEW)).toBeInTheDocument();
  });

  it("never lets an older run that settles late overwrite a newer one", async () => {
    // A second ask while the first is in flight (the context aborts the first itself); the
    // first run's cancellation only settles after the second run has answered.
    const { fetchImpl } = slowFirstRun(100);
    function AskTwice() {
      const { ask: askAgent } = useAgent();
      return (
        <button
          type="button"
          onClick={() => {
            void askAgent("First question", { includeFile: false, includeSelection: false });
            void askAgent("Second question", { includeFile: false, includeSelection: false });
          }}
        >
          ask-twice
        </button>
      );
    }
    vi.stubGlobal("fetch", fetchImpl);
    render(
      <WorkspaceProviders>
        <Harness>
          <AskTwice />
          <AgentPanel />
        </Harness>
      </WorkspaceProviders>,
    );
    await userEvent.click(await screen.findByRole("button", { name: "ask-twice" }));
    expect(await screen.findByText(NEW)).toBeInTheDocument();
    await new Promise((resolve) => setTimeout(resolve, 200)); // run 1's rejection lands now
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByText(NEW)).toBeInTheDocument();
  });
});

describe("Agent workflows (Module 17)", () => {
  const FINDINGS = [
    {
      id: "F1",
      severity: "low",
      category: "maintainability",
      title: "Loop could be a sum()",
      file_path: PATH,
      start_line: 2,
      end_line: 3,
      explanation: "A generator with sum() is clearer.",
      evidence: "for item in items:",
      suggestion: "Use sum(item.price for item in items).",
      confidence: "medium",
      excerpt: ["    for item in items:"],
    },
    {
      id: "F2",
      severity: "high",
      category: "bug",
      title: "total used before assignment",
      file_path: PATH,
      start_line: 3,
      end_line: 3,
      explanation: "Raises UnboundLocalError on the first item.",
      evidence: "total += item.price",
      suggestion: "Initialise total = 0.",
      confidence: "high",
      excerpt: ["        total += item.price"],
    },
  ];
  const REVIEW_RUN = {
    ...RUN,
    mode: "review",
    actions: [],
    findings: FINDINGS,
    usage: {
      provider_calls: 3,
      input_tokens: 1200,
      output_tokens: 300,
      tool_calls: 2,
      largest_prompt_chars: 9000,
    },
    context: { files_inspected: [PATH, "shop/pricing.py"], memory_items: 2 },
  };

  it("runs the chosen workflow and shows findings by severity with their evidence", async () => {
    const fetchMock = renderAgent([
      ["GET", /^\/agent\/status$/, () => STATUS(true)],
      ["POST", /^\/agent\/run$/, () => json(REVIEW_RUN)],
    ]);
    await userEvent.selectOptions(await screen.findByLabelText("Workflow"), "review");
    await ask("Review this file");
    const findings = await screen.findByRole("region", { name: "Review findings" });
    expect(requestsOf(fetchMock).find((r) => r.path === "/agent/run")!.body.mode).toBe("review");
    expect(within(findings).getByText(/1 high, 1 low/)).toBeInTheDocument();
    const items = within(findings).getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("high"); // highest severity first, labelled in text
    expect(items[0]).toHaveTextContent("Evidence: total += item.price");
    expect(
      screen.getByText(/2 files inspected · 2 project note\(s\) · 3 model call\(s\), 1,500 tokens/),
    ).toBeInTheDocument();
  });

  it("asks for a fix for one finding as a new request", async () => {
    const fetchMock = renderAgent([
      ["GET", /^\/agent\/status$/, () => STATUS(true)],
      ["POST", /^\/agent\/run$/, () => json(REVIEW_RUN)],
    ]);
    await ask("Review this file");
    const findings = await screen.findByRole("region", { name: "Review findings" });
    await userEvent.click(within(findings).getAllByRole("button", { name: "Propose fix" })[0]);
    await waitFor(() =>
      expect(requestsOf(fetchMock).filter((r) => r.path === "/agent/run")).toHaveLength(2),
    );
    const second = requestsOf(fetchMock).filter((r) => r.path === "/agent/run")[1];
    expect(second.body.mode).toBe("assist");
    expect(String(second.body.message)).toContain("total used before assignment");
    expect(String(second.body.message)).toContain(`${PATH}:3`);
  });

  it("applies a multi-file change only as a whole", async () => {
    const other = { ...ACTION, id: "a2", file_path: "shop/pricing.py", summary: ACTION.summary };
    const grouped = [ACTION, other].map((a) => ({
      ...a,
      group_id: "g1",
      group_size: 2,
      risk: "low",
    }));
    const fetchMock = renderAgent([
      ["GET", /^\/agent\/status$/, () => STATUS(true)],
      ["POST", /^\/agent\/run$/, () => json({ ...RUN, actions: grouped })],
      [
        "POST",
        /^\/agent\/groups\/g1\/approve$/,
        () =>
          json({
            group_id: "g1",
            actions: grouped.map((a) => ({ ...a, status: "applied" })),
            files: [
              {
                action_id: "a1",
                file: { file_id: "f1", path: PATH, content: FIXED, content_hash: "h2", version: 2 },
                diagnostic_count: 0,
              },
            ],
          }),
      ],
      ["GET", /^\/projects\/p1\/files$/, () => json({ ...page([FILE]), limit: 5000 })],
    ]);
    await ask("Rename it");
    const card = await screen.findByRole("listitem", { name: "Proposed change to 2 files" });
    expect(within(card).getByText(/2 files, applied together · risk low/)).toBeInTheDocument();
    expect(within(card).queryByRole("button", { name: "Apply" })).not.toBeInTheDocument();
    await userEvent.click(within(card).getByRole("button", { name: "Apply all 2 files" }));
    await waitFor(() => expect(screen.getByTestId("buffer").textContent).toBe(FIXED));
    expect(requestsOf(fetchMock).some((r) => r.path === "/agent/groups/g1/approve")).toBe(true);
    expect(requestsOf(fetchMock).some((r) => r.path.startsWith("/agent/actions/"))).toBe(false);
  });

  it("labels a new-file proposal and shows its content before it is created", async () => {
    const created = {
      ...ACTION,
      id: "a3",
      kind: "create_file",
      file_path: "tests/test_cart.py",
      summary: "Tests for cart_total",
      diff: "--- /dev/null\n+++ b/tests/test_cart.py\n@@ -0,0 +1,2 @@\n+def test_empty():\n+    assert True\n",
    };
    renderAgent([
      ["GET", /^\/agent\/status$/, () => STATUS(true)],
      ["POST", /^\/agent\/run$/, () => json({ ...RUN, actions: [created] })],
    ]);
    await ask("Generate tests");
    const card = await screen.findByRole("listitem", {
      name: "Proposed new file tests/test_cart.py",
    });
    expect(within(card).getByText("new file")).toBeInTheDocument();
    expect(within(card).getByRole("button", { name: "Create file" })).toBeEnabled();
    expect(within(card).queryByRole("button", { name: "Review diff" })).not.toBeInTheDocument();
    expect(within(card).getByText("+def test_empty():")).toBeInTheDocument();
  });
});
