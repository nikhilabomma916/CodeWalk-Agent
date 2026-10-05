// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect, useRef, type ReactNode } from "react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import { WorkspaceProviders } from "@/features/workspace/workspace";
import { useWorkspace } from "@/features/workspace/workspace-context";
import { detectLanguage } from "@/lib/languages";
import { apiError, fakeBackend, json, makeProject, page, requestsOf } from "@/testing/fake-api";

import { ProjectExplorer } from "./project-explorer";

const EXISTING = {
  id: "f1",
  project_id: "p1",
  path: "src/app.py",
  name: "app.py",
  language: "python",
  size: 0,
  line_count: 0,
  content_hash: "h",
  has_content: true,
  created_at: "2026-10-01T00:00:00Z",
  updated_at: "2026-10-01T00:00:00Z",
};

function Harness({ children }: { children: ReactNode }) {
  const { state, actions } = useWorkspace();
  const started = useRef(false);
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    void actions.openServerProject(makeProject());
  }, [actions]);
  return state.project ? <>{children}</> : null;
}

function ActiveFile() {
  const { state } = useWorkspace();
  return (
    <p data-testid="active">
      {state.activePath ?? "none"}|{state.activePath ? detectLanguage(state.activePath) : ""}
    </p>
  );
}

function renderExplorer() {
  const fetchMock = fakeBackend([
    ["GET", /^\/projects\/p1\/files$/, () => json({ ...page([EXISTING]), limit: 5000 })],
    [
      "POST",
      /^\/projects\/p1\/files\/code-file$/,
      (_url, raw) => {
        const { name } = raw as { name: string };
        if (name === "main.py") return apiError(409, "file_exists", "main.py already exists.");
        return json(
          {
            file: { ...EXISTING, id: "f2", path: name, name, content: "" },
            analysis: null,
          },
          201,
        );
      },
    ],
    [
      "GET",
      /^\/projects\/p1\/files\/f2$/,
      () => json({ ...EXISTING, id: "f2", path: "demo.py", name: "demo.py", content: "" }),
    ],
  ]);
  vi.stubGlobal("fetch", fetchMock);
  render(
    <WorkspaceProviders>
      <Harness>
        <ProjectExplorer />
        <ActiveFile />
      </Harness>
    </WorkspaceProviders>,
  );
  return fetchMock;
}

beforeAll(() => {
  HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
});
afterEach(() => vi.unstubAllGlobals());

describe("Coding + New File", () => {
  it("creates a file from a name only and opens it", async () => {
    const fetchMock = renderExplorer();
    await userEvent.click(await screen.findByRole("button", { name: "New File" }));
    const dialog = screen.getByRole("dialog", { name: "Create code file" });
    expect(within(dialog).queryByRole("combobox")).not.toBeInTheDocument(); // no folder selector
    await userEvent.type(within(dialog).getByLabelText("File name"), "demo.py");
    await userEvent.click(within(dialog).getByRole("button", { name: "Create" }));

    await waitFor(() => expect(screen.getByTestId("active")).toHaveTextContent("demo.py|python"));
    expect(dialog).not.toHaveAttribute("open");
    const request = requestsOf(fetchMock).find((r) => r.path === "/projects/p1/files/code-file")!;
    expect(request.body).toEqual({ name: "demo.py" });
    // The existing folder structure is untouched.
    expect(screen.getByRole("treeitem", { name: "src" })).toBeInTheDocument();
  });

  it("rejects unsupported types and folders before sending anything", async () => {
    const fetchMock = renderExplorer();
    await userEvent.click(await screen.findByRole("button", { name: "New File" }));
    const dialog = screen.getByRole("dialog", { name: "Create code file" });
    const input = within(dialog).getByLabelText("File name");
    await userEvent.type(input, "setup.exe");
    await userEvent.click(within(dialog).getByRole("button", { name: "Create" }));
    expect(within(dialog).getByRole("alert")).toHaveTextContent("Unsupported file type");
    await userEvent.clear(input);
    await userEvent.type(input, "../../evil.py");
    await userEvent.click(within(dialog).getByRole("button", { name: "Create" }));
    expect(within(dialog).getByRole("alert")).toHaveTextContent("without folders");
    expect(requestsOf(fetchMock).some((r) => r.path.endsWith("/code-file"))).toBe(false);
  });

  it("never overwrites: a taken name offers to open the existing file", async () => {
    renderExplorer();
    await userEvent.click(await screen.findByRole("button", { name: "New File" }));
    const dialog = screen.getByRole("dialog", { name: "Create code file" });
    await userEvent.type(within(dialog).getByLabelText("File name"), "main.py");
    await userEvent.click(within(dialog).getByRole("button", { name: "Create" }));
    expect(await within(dialog).findByText("main.py already exists.")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Open existing file" })).toBeInTheDocument();
    expect(screen.getByTestId("active")).toHaveTextContent("none");
  });
});
