// @vitest-environment jsdom
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect, useRef, type ComponentProps, type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ProblemsPanel } from "@/features/problems/problems-panel";
import { WorkspaceProviders } from "@/features/workspace/workspace";
import { useWorkspace } from "@/features/workspace/workspace-context";
import { apiError, fakeBackend, json, requestsOf, type Route } from "@/testing/fake-api";
import type { Diagnostic } from "@/types/diagnostics";

import { AIReviewPanel } from "./ai-review-panel";
import { FixReview } from "./fix-review";

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

const CODE = "def total(items):\n    for item in items:\n        total += item\n    return total\n";
const FIXED =
  "def total(items):\n    total = 0\n    for item in items:\n        total += item\n    return total\n";

const DIAGNOSTIC: Diagnostic = {
  id: "d1",
  severity: "error",
  category: "lint",
  message: "Undefined name `total`",
  file: "app.py",
  line: 3,
  column: 9,
  endLine: 3,
  endColumn: 14,
  source: "ruff",
  code: "F821",
  fixable: false,
  unnecessary: false,
};

const status = (available: boolean) =>
  json({
    enabled: available,
    configured: available,
    available,
    provider: available ? "anthropic" : null,
    model: available ? "claude-opus-5-5" : null,
    detail: available
      ? null
      : "AI assistance is turned off (set CODEWALK_AI_ENABLED=true to enable it).",
    analysis_types: ["general_review", "bug_detection"],
  });

const base = {
  request_id: "r1",
  provider: "anthropic",
  model: "claude-opus-5-5",
  generated_at: "2026-10-02T10:00:00Z",
  confidence: "high",
  warnings: [],
  context: { used: false, files: [], symbols: [], snippet_count: 0, truncated: false },
  record_id: null,
};

const explanation = {
  ...base,
  diagnostic_id: "d1",
  problem: "Undefined name `total`",
  explanation: "`total` is read before anything is assigned to it.",
  cause: "The accumulator is never initialised.",
  impact: "Calling the function raises NameError.",
  suggested_fix: "Set `total = 0` before the loop.",
  related_code_locations: [{ file_path: "app.py", line: 2, reason: "the loop that uses it" }],
};

const suggestion = {
  ...base,
  status: "suggested",
  summary: "Initialise the accumulator.",
  explanation: "Adds total = 0 before the loop.",
  file_path: "app.py",
  original_code: CODE,
  original_hash: "h",
  suggested_code: FIXED,
  diff: "--- a/app.py\n+++ b/app.py\n@@ -1,4 +1,5 @@\n def total(items):\n+    total = 0\n",
  edits: [],
};

/** Opens an in-memory project with app.py (CODE) and one diagnostic, then renders children. */
function Harness({ children }: { children: ReactNode }) {
  const { state, actions } = useWorkspace();
  const started = useRef(false);
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    void (async () => {
      await actions.createProject("Demo");
      await actions.createFile("app.py");
      actions.editFile("app.py", CODE);
      actions.replaceDiagnostics("analysis", "app.py", [DIAGNOSTIC]);
    })();
  }, [actions]);
  const buffer = state.buffers["app.py"];
  return (
    <>
      <div data-testid="buffer">{buffer?.content}</div>
      {state.project && buffer ? children : null}
    </>
  );
}

function renderWith(routes: Route[], ui: ReactNode) {
  const fetchMock = fakeBackend(routes);
  vi.stubGlobal("fetch", fetchMock);
  render(
    <WorkspaceProviders>
      <Harness>{ui}</Harness>
    </WorkspaceProviders>,
  );
  return fetchMock;
}

afterEach(() => vi.unstubAllGlobals());

describe("Explain with AI", () => {
  it("explains the selected problem with the editor's current code", async () => {
    const fetchMock = renderWith(
      [
        ["GET", /^\/ai\/status$/, () => status(true)],
        ["POST", /^\/ai\/explain$/, () => json(explanation)],
      ],
      <ProblemsPanel />,
    );
    await userEvent.click(
      await screen.findByRole("button", { name: "Explain with AI: Undefined name `total`" }),
    );
    const panel = await screen.findByRole("complementary", { name: "AI explanation" });
    expect(
      await within(panel).findByText("The accumulator is never initialised."),
    ).toBeInTheDocument();
    expect(within(panel).getByText("Calling the function raises NameError.")).toBeInTheDocument();
    expect(within(panel).getByText("Set `total = 0` before the loop.")).toBeInTheDocument();
    expect(within(panel).getByText("high confidence")).toBeInTheDocument();
    expect(within(panel).getByText(/AI output is advisory/)).toBeInTheDocument();

    const sent = requestsOf(fetchMock).find((r) => r.path === "/ai/explain")!;
    expect(sent.body).toMatchObject({
      code: CODE,
      file_path: "app.py",
      diagnostic: { id: "d1", line: 3, column: 9, end_line: 3, end_column: 14, code: "F821" },
    });
    expect(sent.body.project_id).toBeUndefined(); // an in-memory project has no server id
  });

  it("shows when AI is unavailable instead of an answer", async () => {
    renderWith(
      [
        ["GET", /^\/ai\/status$/, () => status(false)],
        [
          "POST",
          /^\/ai\/explain$/,
          () => apiError(503, "ai_disabled", "AI assistance is turned off on this server."),
        ],
      ],
      <ProblemsPanel />,
    );
    await userEvent.click(await screen.findByRole("button", { name: /Explain with AI/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "AI unavailable: AI assistance is turned off on this server.",
    );
  });

  it("reports provider errors", async () => {
    renderWith(
      [
        ["GET", /^\/ai\/status$/, () => status(true)],
        [
          "POST",
          /^\/ai\/explain$/,
          () => apiError(504, "ai_timeout", "The AI provider did not answer in time."),
        ],
      ],
      <ProblemsPanel />,
    );
    await userEvent.click(await screen.findByRole("button", { name: /Explain with AI/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("did not answer in time");
  });
});

describe("Fix suggestion review", () => {
  function renderFixFlow(fixResponse: () => Response) {
    return renderWith(
      [
        ["GET", /^\/ai\/status$/, () => status(true)],
        ["POST", /^\/ai\/explain$/, () => json(explanation)],
        ["POST", /^\/ai\/fix-suggestion$/, fixResponse],
      ],
      <>
        <ProblemsPanel />
        <div style={{ position: "relative" }}>
          <FixReview path="app.py" />
        </div>
      </>,
    );
  }

  async function requestFix() {
    await userEvent.click(await screen.findByRole("button", { name: /Explain with AI/ }));
    await userEvent.click(await screen.findByRole("button", { name: "Suggest a fix" }));
    return screen.findByRole("region", { name: "Review AI fix" });
  }

  it("shows current versus suggested code and changes nothing until Apply", async () => {
    const fetchMock = renderFixFlow(() => json(suggestion));
    const review = await requestFix();
    expect(within(review).getByText("Current code")).toBeInTheDocument();
    expect(within(review).getByText("Suggested code")).toBeInTheDocument();
    expect(screen.getByTestId("diff")).toHaveTextContent(
      `${CODE}=>${FIXED}`.replace(/\s+/g, " ").trim(),
      {
        normalizeWhitespace: true,
      },
    );
    expect(within(review).getByText(/1 changed line/)).toBeInTheDocument();
    // Not applied yet: the editor buffer is untouched.
    expect(screen.getByTestId("buffer").textContent).toBe(CODE);
    expect(requestsOf(fetchMock).find((r) => r.path === "/ai/fix-suggestion")!.body).toMatchObject({
      code: CODE,
      diagnostic: { id: "d1" },
    });

    await userEvent.click(within(review).getByRole("button", { name: "Apply fix" }));
    expect(screen.getByTestId("buffer").textContent).toBe(FIXED);
    expect(screen.queryByRole("region", { name: "Review AI fix" })).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Fix applied to the editor (not saved yet)",
    );
    // The fix only changed the editor: no save request was made.
    expect(requestsOf(fetchMock).some((r) => r.method === "PATCH")).toBe(false);
  });

  it("rejecting leaves the code as it was", async () => {
    renderFixFlow(() => json(suggestion));
    const review = await requestFix();
    await userEvent.click(within(review).getByRole("button", { name: "Reject" }));
    expect(screen.queryByRole("region", { name: "Review AI fix" })).not.toBeInTheDocument();
    expect(screen.getByText("Suggestion rejected.")).toBeInTheDocument();
    expect(screen.getByTestId("buffer").textContent).toBe(CODE);
  });

  it("can be closed and reopened without deciding", async () => {
    renderFixFlow(() => json(suggestion));
    const review = await requestFix();
    await userEvent.click(within(review).getByRole("button", { name: "Close review" }));
    expect(screen.queryByRole("region", { name: "Review AI fix" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Review suggested fix" }));
    expect(screen.getByRole("region", { name: "Review AI fix" })).toBeInTheDocument();
    expect(screen.getByTestId("buffer").textContent).toBe(CODE);
  });

  it("refuses to apply after the file changed", async () => {
    let edit: ((content: string) => void) | undefined;
    function Editor() {
      const { actions } = useWorkspace();
      useEffect(() => {
        edit = (content) => actions.editFile("app.py", content);
      }, [actions]);
      return null;
    }
    renderWith(
      [
        ["GET", /^\/ai\/status$/, () => status(true)],
        ["POST", /^\/ai\/explain$/, () => json(explanation)],
        ["POST", /^\/ai\/fix-suggestion$/, () => json(suggestion)],
      ],
      <>
        <Editor />
        <ProblemsPanel />
        <FixReview path="app.py" />
      </>,
    );
    const review = await requestFix();
    act(() => edit!(`${CODE}# edited meanwhile\n`));
    expect(within(review).getByRole("button", { name: "Apply fix" })).toBeDisabled();
    expect(within(review).getByRole("alert")).toHaveTextContent("changed after this suggestion");
    expect(screen.getByTestId("buffer").textContent).toBe(`${CODE}# edited meanwhile\n`);
  });

  it("explains when there is no useful suggestion", async () => {
    renderFixFlow(() =>
      json({
        ...suggestion,
        status: "no_suggestion",
        suggested_code: CODE,
        diff: "",
        warnings: ["The fix needs a change in another file."],
      }),
    );
    await userEvent.click(await screen.findByRole("button", { name: /Explain with AI/ }));
    await userEvent.click(await screen.findByRole("button", { name: "Suggest a fix" }));
    expect(
      await screen.findByText(/No useful fix suggestion\. The fix needs a change/),
    ).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Review AI fix" })).not.toBeInTheDocument();
  });
});

describe("AI review panel", () => {
  function renderReview(
    routes: Route[],
    props: Partial<ComponentProps<typeof AIReviewPanel>> = {},
  ) {
    function Activate() {
      const { state, actions } = useWorkspace();
      useEffect(() => {
        if (state.activePath !== "app.py") actions.activateTab("app.py");
      }, [actions, state.activePath]);
      return (
        <div data-testid="reveal">
          {state.reveal ? `${state.reveal.path}:${state.reveal.line}` : ""}
        </div>
      );
    }
    return renderWith(
      routes,
      <>
        <Activate />
        <AIReviewPanel {...props} />
      </>,
    );
  }

  it("is disabled with the reason when AI is unavailable", async () => {
    renderReview([["GET", /^\/ai\/status$/, () => status(false)]]);
    expect(
      await screen.findByText(/AI unavailable: AI assistance is turned off/),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Review/ })).toBeDisabled();
  });

  it("reviews the file and lists findings that link to the code", async () => {
    const fetchMock = renderReview([
      ["GET", /^\/ai\/status$/, () => status(true)],
      [
        "POST",
        /^\/ai\/analyze$/,
        () =>
          json({
            ...base,
            confidence: "medium",
            analysis_type: "bug_detection",
            summary: "One likely bug.",
            findings: [
              {
                id: "ai-1",
                severity: "warning",
                category: "bug",
                title: "Accumulator never initialised",
                description: "total is used before assignment.",
                reasoning: "No assignment precedes the +=.",
                basis: "observed",
                file_path: "app.py",
                line: 3,
                column: 9,
                end_line: 3,
                end_column: 22,
                confidence: "high",
                suggestion: "Initialise it.",
                related_diagnostic_id: "d1",
                metadata: { evidence: "total += item" },
              },
            ],
          }),
      ],
    ]);
    await userEvent.selectOptions(await screen.findByLabelText("Focus"), "bug_detection");
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Review app.py" })).toBeEnabled(),
    );
    await userEvent.click(screen.getByRole("button", { name: "Review app.py" }));
    const findings = await screen.findByRole("list", { name: "AI findings" });
    expect(within(findings).getByText("Accumulator never initialised")).toBeInTheDocument();
    expect(screen.getByText("One likely bug.")).toBeInTheDocument();
    expect(requestsOf(fetchMock).find((r) => r.path === "/ai/analyze")!.body).toMatchObject({
      analysis_type: "bug_detection",
      code: CODE,
    });

    await userEvent.click(
      within(findings).getByRole("button", { name: /Accumulator never initialised/ }),
    );
    expect(within(findings).getByText("No assignment precedes the +=.")).toBeInTheDocument();
    await userEvent.click(within(findings).getByRole("button", { name: "Go to line 3" }));
    expect(screen.getByTestId("reveal").textContent).toBe("app.py:3");
  });
});
