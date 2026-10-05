// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect, useRef, type ReactNode } from "react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import { WorkspaceProviders } from "@/features/workspace/workspace";
import { useWorkspace } from "@/features/workspace/workspace-context";
import { fakeBackend, json, makeProject, page, requestsOf, type Route } from "@/testing/fake-api";

import { FileHistoryPanel } from "./file-history-panel";

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

beforeAll(() => {
  HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
});
afterEach(() => vi.unstubAllGlobals());

const FILE = {
  id: "f1",
  project_id: "p1",
  path: "shop/cart.py",
  name: "cart.py",
  language: "python",
  size: 10,
  line_count: 2,
  content_hash: "h",
  has_content: true,
  created_at: "2026-10-05T00:00:00Z",
  updated_at: "2026-10-05T00:00:00Z",
};

const version = (n: number, source: string) => ({
  version: n,
  size: 10,
  line_count: 2,
  content_hash: `h${n}`,
  source,
  author_id: null,
  created_at: `2026-10-05T0${n}:00:00Z`,
});

const AI_ACTION = {
  id: "a1",
  run_id: "r1",
  kind: "code_change",
  group_id: null,
  group_size: 1,
  confidence: "high",
  risk: "low",
  status: "applied",
  file_path: "shop/cart.py",
  summary: "Initialise total before the loop",
  explanation: "total is used before assignment.",
  changes: [],
  diff: "--- a\n+++ b\n-x = total\n+total = 0",
  base_content_hash: "h1",
  validation: "ok",
  created_at: "2026-10-05T02:00:00Z",
  decided_at: "2026-10-05T02:00:00Z",
  result: { version: 2, created: false },
};

function Harness({ children }: { children: ReactNode }) {
  const { state, actions } = useWorkspace();
  const started = useRef(false);
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    void (async () => {
      await actions.openServerProject(makeProject());
      await actions.openFile("shop/cart.py");
    })();
  }, [actions]);
  const buffer = state.buffers["shop/cart.py"];
  return (
    <>
      <output data-testid="content">{buffer?.content}</output>
      {buffer?.status === "ready" ? children : null}
    </>
  );
}

function renderPanel(routes: Route[]) {
  const fetchMock = fakeBackend([
    ["GET", /^\/projects\/p1\/files$/, () => json({ ...page([FILE]), limit: 5000 })],
    ["GET", /^\/projects\/p1\/files\/f1$/, () => json({ ...FILE, content: "total = 0\n" })],
    ...routes,
  ]);
  vi.stubGlobal("fetch", fetchMock);
  render(
    <WorkspaceProviders>
      <Harness>
        <FileHistoryPanel />
      </Harness>
    </WorkspaceProviders>,
  );
  return fetchMock;
}

describe("File history", () => {
  it("lists versions, marks the AI change, compares and restores", async () => {
    const fetchMock = renderPanel([
      [
        "GET",
        /^\/projects\/p1\/files\/f1\/versions$/,
        () => json(page([version(2, "edit"), version(1, "create")])),
      ],
      [
        "GET",
        /^\/projects\/p1\/files\/f1\/versions\/1$/,
        () => json({ ...version(1, "create"), content: "x = total\n" }),
      ],
      [
        "POST",
        /^\/projects\/p1\/files\/f1\/versions\/1\/restore$/,
        () => json({ file: { ...FILE, content: "x = total\n" }, analysis: null }),
      ],
      ["GET", /^\/agent\/actions$/, () => json(page([AI_ACTION]))],
    ]);
    const list = await screen.findByRole("list", { name: "Versions of shop/cart.py" });
    const items = within(list).getAllByRole("listitem");
    expect(items[0]).toHaveTextContent(/v2\s*AI change\s*current/);
    expect(items[0]).toHaveTextContent("Initialise total before the loop");
    expect(items[1]).toHaveTextContent(/v1\s*Created/);

    await userEvent.click(within(items[1]).getByRole("button", { name: "Compare with editor" }));
    expect(await screen.findByTestId("diff")).toHaveTextContent("x = total =>total = 0");

    await userEvent.click(within(items[1]).getByRole("button", { name: "Restore" }));
    const confirm = await screen.findByRole("dialog", { name: /Restore version 1/ });
    await userEvent.click(within(confirm).getByRole("button", { name: "Restore" }));
    await waitFor(() => expect(screen.getByTestId("content")).toHaveTextContent("x = total"));
    expect(
      requestsOf(fetchMock).some((r) => r.path === "/projects/p1/files/f1/versions/1/restore"),
    ).toBe(true);
  });

  it("lists AI changes with their reason and undoes an applied one", async () => {
    let undone = false;
    const fetchMock = renderPanel([
      ["GET", /^\/projects\/p1\/files\/f1\/versions$/, () => json(page([version(1, "create")]))],
      [
        "GET",
        /^\/agent\/actions$/,
        () => json(page([{ ...AI_ACTION, result: { ...AI_ACTION.result, undone } }])),
      ],
      [
        "POST",
        /^\/agent\/actions\/a1\/undo$/,
        () => {
          undone = true;
          return json({
            action: { ...AI_ACTION, result: { ...AI_ACTION.result, undone: true } },
            file: {
              file_id: "f1",
              path: "shop/cart.py",
              content: "x = total\n",
              content_hash: "h3",
              version: 3,
            },
            deleted: false,
          });
        },
      ],
    ]);
    const changes = await screen.findByRole("list", { name: /AI changes in this project/ });
    const item = within(changes).getByRole("listitem");
    expect(item).toHaveTextContent("Initialise total before the loop");
    expect(item).toHaveTextContent("applied");
    await userEvent.click(within(item).getByText("Why and diff"));
    expect(within(item).getByText("total is used before assignment.")).toBeInTheDocument();

    await userEvent.click(within(item).getByRole("button", { name: "Undo" }));
    const confirm = await screen.findByRole("dialog", { name: /Undo/ });
    expect(confirm).toHaveTextContent("goes back to its content before this AI change");
    await userEvent.click(within(confirm).getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(screen.getByTestId("content")).toHaveTextContent("x = total"));
    await waitFor(() => expect(within(changes).getByRole("listitem")).toHaveTextContent("undone"));
    expect(requestsOf(fetchMock).some((r) => r.path === "/agent/actions/a1/undo")).toBe(true);
  });

  it("explains that history needs a CodeWalk project", () => {
    vi.stubGlobal("fetch", fakeBackend([]));
    render(
      <WorkspaceProviders>
        <FileHistoryPanel />
      </WorkspaceProviders>,
    );
    expect(screen.getByText(/History is kept for projects stored by CodeWalk/)).toBeInTheDocument();
  });
});
