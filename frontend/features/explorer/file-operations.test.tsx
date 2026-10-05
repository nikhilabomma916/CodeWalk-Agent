// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect, useRef } from "react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import { WorkspaceProviders } from "@/features/workspace/workspace";
import { useWorkspace } from "@/features/workspace/workspace-context";
import { fakeBackend, json, makeProject, page, requestsOf } from "@/testing/fake-api";

import { ProjectExplorer } from "./project-explorer";

beforeAll(() => {
  // jsdom has no <dialog> support.
  HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
});
afterEach(() => vi.unstubAllGlobals());

/** An in-browser project with src/app/{main,db}.py and README.md; main.py open with an unsaved edit. */
function MemoryProject() {
  const { state, actions } = useWorkspace();
  const started = useRef(false);
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    void (async () => {
      await actions.createProject("Demo");
      await actions.createFile("src/app/main.py");
      await actions.createFile("src/app/db.py");
      await actions.createFile("README.md");
      await actions.openFile("src/app/main.py");
      actions.editFile("src/app/main.py", "print('unsaved')\n");
    })();
  }, [actions]);
  return (
    <>
      <output data-testid="paths">
        {state.entries
          .filter((e) => e.type === "file")
          .map((e) => e.path)
          .sort()
          .join(",")}
      </output>
      <output data-testid="active">{state.activePath}</output>
      <output data-testid="active-content">
        {state.activePath ? state.buffers[state.activePath]?.content : ""}
      </output>
      {state.entries.length > 0 && <ProjectExplorer />}
    </>
  );
}

const row = (name: string) => screen.findByRole("treeitem", { name: new RegExp(`^${name}`) });

async function menuFor(name: string) {
  fireEvent.contextMenu(await row(name), { clientX: 10, clientY: 10 });
  return screen.findByRole("menu");
}

async function submitPath(value: string) {
  const dialog = await screen.findByRole("dialog");
  const input = within(dialog).getByRole("textbox");
  await userEvent.clear(input);
  await userEvent.type(input, value);
  await userEvent.click(within(dialog).getByRole("button", { name: /Create|Rename|Move/ }));
}

describe("Explorer file operations (in-browser project)", () => {
  it("renames a folder; the open file follows with its unsaved edit", async () => {
    render(
      <WorkspaceProviders>
        <MemoryProject />
      </WorkspaceProviders>,
    );
    const menu = await menuFor("app");
    await userEvent.click(within(menu).getByRole("menuitem", { name: /^Rename…/ }));
    await submitPath("src/core");
    await waitFor(() =>
      expect(screen.getByTestId("paths")).toHaveTextContent(
        "README.md,src/core/db.py,src/core/main.py",
      ),
    );
    expect(screen.getByTestId("active")).toHaveTextContent("src/core/main.py");
    expect(screen.getByTestId("active-content")).toHaveTextContent("print('unsaved')");
  });

  it("creates files and folders, duplicates, and deletes after confirmation", async () => {
    render(
      <WorkspaceProviders>
        <MemoryProject />
      </WorkspaceProviders>,
    );
    // New file inside a folder (the dialog starts with the folder path).
    let menu = await menuFor("app");
    await userEvent.click(within(menu).getByRole("menuitem", { name: "New File…" }));
    expect(within(await screen.findByRole("dialog")).getByRole("textbox")).toHaveValue("src/app/");
    await submitPath("src/app/routes.py");
    await waitFor(() => expect(screen.getByTestId("paths")).toHaveTextContent("src/app/routes.py"));

    // New folder (kept with a .gitkeep).
    await userEvent.click(screen.getByRole("button", { name: "New folder" }));
    await submitPath("tests");
    await waitFor(() => expect(screen.getByTestId("paths")).toHaveTextContent("tests/.gitkeep"));

    // Duplicate copies the current editor content.
    menu = await menuFor("main.py");
    await userEvent.click(within(menu).getByRole("menuitem", { name: "Duplicate" }));
    await waitFor(() =>
      expect(screen.getByTestId("active")).toHaveTextContent("src/app/main copy.py"),
    );
    expect(screen.getByTestId("active-content")).toHaveTextContent("print('unsaved')");

    // Delete asks first; cancelling keeps the file.
    menu = await menuFor("README.md");
    await userEvent.click(within(menu).getByRole("menuitem", { name: /^Delete…/ }));
    let confirm = await screen.findByRole("dialog", { name: /Delete README\.md/ });
    await userEvent.click(within(confirm).getByRole("button", { name: "Cancel" }));
    expect(screen.getByTestId("paths")).toHaveTextContent("README.md");
    menu = await menuFor("README.md");
    await userEvent.click(within(menu).getByRole("menuitem", { name: /^Delete…/ }));
    confirm = await screen.findByRole("dialog", { name: /Delete README\.md/ });
    await userEvent.click(within(confirm).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(screen.getByTestId("paths")).not.toHaveTextContent("README.md"));
  });

  it("refuses moving a folder into itself and shows why", async () => {
    render(
      <WorkspaceProviders>
        <MemoryProject />
      </WorkspaceProviders>,
    );
    const menu = await menuFor("app");
    await userEvent.click(within(menu).getByRole("menuitem", { name: "Move…" }));
    await submitPath("src/app/inner");
    expect(await within(screen.getByRole("dialog")).findByRole("alert")).toHaveTextContent(
      "A folder cannot be moved into itself.",
    );
    expect(screen.getByTestId("paths")).toHaveTextContent("src/app/main.py");
  });

  it("supports the keyboard: Shift+F10 opens the menu, Escape closes it", async () => {
    render(
      <WorkspaceProviders>
        <MemoryProject />
      </WorkspaceProviders>,
    );
    const item = await row("README.md");
    fireEvent.click(item); // makes it the current row of the tree
    fireEvent.keyDown(item, { key: "F10", shiftKey: true });
    const menu = await screen.findByRole("menu", { name: "Actions for README.md" });
    expect(within(menu).getByRole("menuitem", { name: "Open" })).toHaveFocus();
    fireEvent.keyDown(menu, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("menu")).not.toBeInTheDocument());
  });
});

describe("Explorer file operations (server project)", () => {
  const FILE = (path: string, id: string) => ({
    id,
    project_id: "p1",
    path,
    name: path.split("/").pop(),
    language: "python",
    size: 1,
    line_count: 1,
    content_hash: "h",
    has_content: true,
    created_at: "2026-10-05T00:00:00Z",
    updated_at: "2026-10-05T00:00:00Z",
  });

  function ServerProject() {
    const { state, actions } = useWorkspace();
    const started = useRef(false);
    useEffect(() => {
      if (started.current) return;
      started.current = true;
      void actions.openServerProject(makeProject());
    }, [actions]);
    return (
      <>
        <output data-testid="paths">
          {state.entries
            .filter((e) => e.type === "file")
            .map((e) => e.path)
            .join(",")}
        </output>
        {state.entries.length > 0 && <ProjectExplorer />}
      </>
    );
  }

  it("renames and deletes through the server, in one request each", async () => {
    let files = [FILE("app/main.py", "f1"), FILE("app/db.py", "f2")];
    const fetchMock = fakeBackend([
      ["GET", /^\/projects\/p1\/files$/, () => json({ ...page(files), limit: 5000 })],
      [
        "POST",
        /^\/projects\/p1\/files\/rename-path$/,
        () => {
          files = [FILE("core/main.py", "f1"), FILE("core/db.py", "f2")];
          return json({ paths: ["core/db.py", "core/main.py"] });
        },
      ],
      [
        "POST",
        /^\/projects\/p1\/files\/delete-path$/,
        () => {
          files = files.filter((f) => f.path !== "core/db.py");
          return json({ paths: ["core/db.py"] });
        },
      ],
    ]);
    vi.stubGlobal("fetch", fetchMock);
    render(
      <WorkspaceProviders>
        <ServerProject />
      </WorkspaceProviders>,
    );
    let menu = await menuFor("app");
    await userEvent.click(within(menu).getByRole("menuitem", { name: /^Rename…/ }));
    await submitPath("core");
    await waitFor(() => expect(screen.getByTestId("paths")).toHaveTextContent("core/main.py"));
    expect(requestsOf(fetchMock).find((r) => r.path.endsWith("/rename-path"))?.body).toEqual({
      from_path: "app",
      to_path: "core",
    });

    fireEvent.click(await row("core")); // expand
    menu = await menuFor("db.py");
    await userEvent.click(within(menu).getByRole("menuitem", { name: /^Delete…/ }));
    const confirm = await screen.findByRole("dialog", { name: /Delete core\/db\.py/ });
    expect(confirm).toHaveTextContent(/history .* is removed/);
    await userEvent.click(within(confirm).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(screen.getByTestId("paths")).toHaveTextContent(/^core\/main\.py$/));
    expect(requestsOf(fetchMock).find((r) => r.path.endsWith("/delete-path"))?.body).toEqual({
      path: "core/db.py",
    });
  });

  it("shows the server's reason when a rename target is taken", async () => {
    const fetchMock = fakeBackend([
      [
        "GET",
        /^\/projects\/p1\/files$/,
        () => json({ ...page([FILE("a.py", "f1"), FILE("b.py", "f2")]), limit: 5000 }),
      ],
      [
        "POST",
        /^\/projects\/p1\/files\/rename-path$/,
        () => json({ error: { code: "file_exists", message: "b.py already exists." } }, 409),
      ],
    ]);
    vi.stubGlobal("fetch", fetchMock);
    render(
      <WorkspaceProviders>
        <ServerProject />
      </WorkspaceProviders>,
    );
    const menu = await menuFor("a.py");
    await userEvent.click(within(menu).getByRole("menuitem", { name: /^Rename…/ }));
    await submitPath("b.py");
    expect(await within(screen.getByRole("dialog")).findByRole("alert")).toHaveTextContent(
      "b.py already exists.",
    );
  });
});
