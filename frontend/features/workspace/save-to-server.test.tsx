// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect, useRef } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AgentPanel } from "@/features/agent/agent-panel";
import { fakeBackend, json, makeProject, page, requestsOf } from "@/testing/fake-api";

import { WorkspaceProviders } from "./workspace";
import { useWorkspace } from "./workspace-context";

const FILE = (path: string, id: string) => ({
  id,
  project_id: "p9",
  path,
  name: path.split("/").pop(),
  language: "python",
  size: 10,
  line_count: 1,
  content_hash: "h",
  has_content: true,
  created_at: "2026-10-05T00:00:00Z",
  updated_at: "2026-10-05T00:00:00Z",
});

/** A browser-only project with one saved and one unsaved file, and the agent panel. */
function BrowserProject() {
  const { state, actions } = useWorkspace();
  const started = useRef(false);
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    void (async () => {
      await actions.createProject("Scratch");
      await actions.createFile("app/main.py");
      await actions.createFile("notes.py");
      await actions.openFile("app/main.py");
      actions.editFile("app/main.py", "print('unsaved edit')\n");
    })();
  }, [actions]);
  return (
    <>
      <div data-testid="kind">{state.project?.kind}</div>
      <div data-testid="server-id">{state.project?.serverProjectId ?? "none"}</div>
      {state.project && <AgentPanel />}
    </>
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("Saving a browser project to CodeWalk", () => {
  it("uploads every file with unsaved edits, then opens it from the server", async () => {
    const fetchMock = fakeBackend([
      [
        "GET",
        /^\/agent\/status$/,
        () => json({ available: true, detail: null, tools: [], max_steps: 8, max_actions: 3 }),
      ],
      ["POST", /^\/projects$/, () => json(makeProject({ id: "p9", name: "Scratch" }), 201)],
      [
        "POST",
        /^\/projects\/p9\/files\/import$/,
        () =>
          json({ created: [FILE("app/main.py", "f1"), FILE("notes.py", "f2")], skipped: [] }, 201),
      ],
      [
        "GET",
        /^\/projects\/p9\/files$/,
        () => json({ ...page([FILE("app/main.py", "f1"), FILE("notes.py", "f2")]), limit: 5000 }),
      ],
    ]);
    vi.stubGlobal("fetch", fetchMock);
    render(
      <WorkspaceProviders>
        <BrowserProject />
      </WorkspaceProviders>,
    );

    expect(await screen.findByText(/only in your browser/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Save to CodeWalk" }));

    await waitFor(() => expect(screen.getByTestId("server-id")).toHaveTextContent("p9"));
    expect(screen.getByTestId("kind")).toHaveTextContent("server");
    const created = requestsOf(fetchMock).find((r) => r.path === "/projects");
    expect(created?.body).toMatchObject({ name: "Scratch" });
    const imported = requestsOf(fetchMock).find((r) => r.path === "/projects/p9/files/import");
    // The open file's unsaved content is what gets stored: nothing is lost.
    expect(imported?.body.files).toEqual(
      expect.arrayContaining([
        { path: "app/main.py", content: "print('unsaved edit')\n" },
        { path: "notes.py", content: "" },
      ]),
    );
    // The agent is now usable on the saved project.
    expect(await screen.findByLabelText("Ask about your project")).toBeEnabled();
  });
});
