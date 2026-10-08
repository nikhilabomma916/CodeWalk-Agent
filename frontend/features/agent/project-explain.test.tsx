// @vitest-environment jsdom
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { EXPLAIN_TOPICS } from "@/services/api/agent";
import { apiError, fakeBackend, json, requestsOf } from "@/testing/fake-api";

import { explainMessage, FormattedAnswer, ProjectExplain } from "./project-explain";

const status = (available = true) => ({
  available,
  detail: available ? null : "AI is turned off on this server.",
  tools: [],
  max_steps: 8,
  max_actions: 3,
  max_tool_calls: 12,
  modes: ["assist", "explain"],
});

function run(answer: string) {
  return {
    id: "r1",
    project_id: "p1",
    mode: "explain",
    findings: [],
    context: { files_inspected: ["app/db.py"], memory_items: 0 },
    status: "completed",
    message: "Explain this project: Database.",
    file_path: null,
    answer,
    provider: "openai",
    model: "gpt-5",
    error: null,
    events: [],
    tool_calls: [],
    actions: [],
    warnings: [],
    duration_ms: 900,
    created_at: "2026-10-08T10:00:00Z",
    completed_at: "2026-10-08T10:00:01Z",
  };
}

const runs = (fetchMock: ReturnType<typeof fakeBackend>) =>
  requestsOf(fetchMock).filter((r) => r.method === "POST" && r.path === "/agent/run");

afterEach(() => vi.unstubAllGlobals());

describe("ProjectExplain", () => {
  it("offers every topic and depth, sends the explain workflow, and shows the grounded answer", async () => {
    const fetchMock = fakeBackend([
      ["GET", /^\/agent\/status$/, () => json(status())],
      [
        "POST",
        /^\/agent\/run$/,
        () => json(run("## Database\n- **PostgreSQL** via `app/db.py`\n- Migrations in alembic")),
      ],
    ]);
    vi.stubGlobal("fetch", fetchMock);
    const onOpen = vi.fn();
    render(<ProjectExplain projectId="p1" onOpen={onOpen} />);

    const topics = screen.getByRole("group", { name: "Topic" });
    expect(within(topics).getAllByRole("button")).toHaveLength(EXPLAIN_TOPICS.length);
    expect(within(topics).getByRole("button", { name: "Overview" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await userEvent.click(within(topics).getByRole("button", { name: "Database" }));
    await userEvent.selectOptions(screen.getByLabelText("Depth"), "deep_dive");
    await userEvent.type(screen.getByLabelText("Focus (optional)"), "migrations");
    await userEvent.click(screen.getByRole("button", { name: "Explain" }));

    const answer = await screen.findByRole("region", { name: "Agent answer" });
    expect(within(answer).getByRole("heading", { name: "Database" })).toBeInTheDocument();
    expect(within(answer).getByText("PostgreSQL").tagName).toBe("STRONG");
    expect(within(answer).getByText("app/db.py", { selector: "code" })).toBeInTheDocument();
    await userEvent.click(within(answer).getByRole("button", { name: "app/db.py" }));
    expect(onOpen).toHaveBeenCalledWith("app/db.py", 1);

    const [request] = runs(fetchMock);
    expect(request.body).toMatchObject({
      project_id: "p1",
      mode: "explain",
      explain_topic: "database",
      explain_depth: "deep_dive",
      message: "Explain this project: Database. Focus on: migrations",
    });
    expect(screen.getByRole("button", { name: "Explain again" })).toBeEnabled();
  });

  it("keeps answers per topic and depth, so switching back needs no new request", async () => {
    const fetchMock = fakeBackend([
      ["GET", /^\/agent\/status$/, () => json(status())],
      ["POST", /^\/agent\/run$/, () => json(run("Overview answer."))],
    ]);
    vi.stubGlobal("fetch", fetchMock);
    render(<ProjectExplain projectId="p1" />);
    const topics = screen.getByRole("group", { name: "Topic" });
    await userEvent.click(screen.getByRole("button", { name: "Explain" }));
    expect(await screen.findByText("Overview answer.")).toBeInTheDocument();

    await userEvent.click(within(topics).getByRole("button", { name: "Testing" }));
    expect(screen.queryByText("Overview answer.")).not.toBeInTheDocument();
    await userEvent.click(within(topics).getByRole("button", { name: "Overview" }));
    expect(screen.getByText("Overview answer.")).toBeInTheDocument();
    expect(runs(fetchMock)).toHaveLength(1);
  });

  it("explains why it cannot run when the agent is unavailable, and shows provider errors", async () => {
    vi.stubGlobal("fetch", fakeBackend([["GET", /^\/agent\/status$/, () => json(status(false))]]));
    const { unmount } = render(<ProjectExplain projectId="p1" />);
    expect(await screen.findByText(/AI is turned off on this server/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Explain" })).toBeDisabled();
    unmount();

    vi.stubGlobal(
      "fetch",
      fakeBackend([
        ["GET", /^\/agent\/status$/, () => json(status())],
        [
          "POST",
          /^\/agent\/run$/,
          () => apiError(502, "ai_quota_exceeded", "The AI provider account has no credit left."),
        ],
      ]),
    );
    render(<ProjectExplain projectId="p1" compact />);
    await userEvent.selectOptions(screen.getByLabelText("Topic"), "security");
    await userEvent.click(screen.getByRole("button", { name: "Explain" }));
    expect(await screen.findByText(/no credit left/)).toBeInTheDocument();
  });
});

describe("FormattedAnswer", () => {
  it("renders a safe Markdown subset as text, never as HTML", () => {
    const { container } = render(
      <FormattedAnswer
        text={"# Title\n1. one\n2. two\n```\n<script>alert(1)</script>\n```\n<b>raw</b>"}
      />,
    );
    expect(screen.getByRole("heading", { name: "Title" })).toBeInTheDocument();
    expect(container.querySelectorAll("ol li")).toHaveLength(2);
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("b")).toBeNull();
    expect(screen.getByText("<b>raw</b>")).toBeInTheDocument();
  });

  it("builds the request message from the topic and optional focus", () => {
    expect(explainMessage("ai_ml", "  ")).toBe("Explain this project: AI/ML.");
    expect(explainMessage("apis", "billing")).toBe("Explain this project: APIs. Focus on: billing");
  });
});
