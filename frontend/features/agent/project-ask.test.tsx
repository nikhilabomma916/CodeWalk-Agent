// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { fakeBackend, json, requestsOf } from "@/testing/fake-api";

import { ProjectAsk } from "./project-ask";

const status = {
  available: true,
  detail: null,
  tools: [],
  max_steps: 8,
  max_actions: 3,
  max_tool_calls: 12,
  modes: ["assist", "architecture"],
};

function run(overrides: Record<string, unknown> = {}) {
  return {
    id: "r1",
    project_id: "p1",
    mode: "assist",
    findings: [],
    context: { files_inspected: ["auth/service.py"], memory_items: 0 },
    status: "completed",
    message: "How does authentication work?",
    file_path: null,
    answer: "Sessions are stored server-side; auth/service.py verifies the cookie.",
    provider: "openai",
    model: "gpt-5",
    error: null,
    events: [],
    tool_calls: [],
    actions: [],
    warnings: [],
    duration_ms: 900,
    created_at: "2026-10-04T10:00:00Z",
    completed_at: "2026-10-04T10:00:01Z",
    ...overrides,
  };
}

const MODES = [
  { id: "assist", label: "Ask a question" },
  { id: "architecture", label: "Explain the architecture" },
] as const;

afterEach(() => vi.unstubAllGlobals());

describe("ProjectAsk", () => {
  it("sends the question and shows only the answer and the files it relied on", async () => {
    const fetchMock = fakeBackend([
      ["GET", /^\/agent\/status$/, () => json(status)],
      ["POST", /^\/agent\/run$/, () => json(run())],
    ]);
    vi.stubGlobal("fetch", fetchMock);
    const onOpen = vi.fn();
    render(<ProjectAsk projectId="p1" modes={MODES} onOpen={onOpen} />);
    const question = screen.getByLabelText("Your question");
    await waitFor(() => expect(question).toBeEnabled());
    await userEvent.type(question, "How does authentication work?");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));

    const answer = await screen.findByRole("region", { name: "Agent answer" });
    expect(within(answer).getByText(/Sessions are stored server-side/)).toBeInTheDocument();
    await userEvent.click(within(answer).getByRole("button", { name: "auth/service.py" }));
    expect(onOpen).toHaveBeenCalledWith("auth/service.py", 1);
    const body = requestsOf(fetchMock).find((r) => r.path === "/agent/run")!.body;
    expect(body).toMatchObject({
      project_id: "p1",
      message: "How does authentication work?",
      mode: "assist",
    });
    expect(body).not.toHaveProperty("file_path"); // no file context unless one is selected
  });

  it("never applies anything: pending proposals are sent to Coding for review", async () => {
    const action = {
      id: "a1",
      run_id: "r1",
      kind: "code_change",
      status: "pending",
      file_path: "auth/service.py",
      summary: "Fix expiry check",
      explanation: "x",
      changes: [],
      diff: "",
      base_content_hash: "h",
      validation: "ok",
      created_at: "2026-10-04T10:00:00Z",
      decided_at: null,
      result: {},
    };
    vi.stubGlobal(
      "fetch",
      fakeBackend([
        ["GET", /^\/agent\/status$/, () => json(status)],
        ["POST", /^\/agent\/run$/, () => json(run({ actions: [action] }))],
      ]),
    );
    render(<ProjectAsk projectId="p1" modes={MODES} />);
    const question = screen.getByLabelText("Your question");
    await waitFor(() => expect(question).toBeEnabled());
    await userEvent.type(question, "Fix the session expiry bug");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));

    const answer = await screen.findByRole("region", { name: "Agent answer" });
    expect(
      within(answer).getByText(/1 proposed change waiting for your review/),
    ).toBeInTheDocument();
    expect(within(answer).getByRole("link", { name: "Review in Coding" })).toHaveAttribute(
      "href",
      "/app/coding?project=p1",
    );
    expect(screen.queryByRole("button", { name: /Apply/ })).not.toBeInTheDocument();
    // Without onOpen, cited files are plain text.
    expect(
      within(answer).queryByRole("button", { name: "auth/service.py" }),
    ).not.toBeInTheDocument();
  });
});
