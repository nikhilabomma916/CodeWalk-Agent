import { describe, expect, it } from "vitest";

import type { Diagnostic } from "@/types/diagnostics";

import {
  createInitialState,
  isDirty,
  workspaceReducer,
  type WorkspaceAction,
  type WorkspaceState,
} from "./state";

function reduce(
  actions: WorkspaceAction[],
  start: WorkspaceState = createInitialState(),
): WorkspaceState {
  return actions.reduce(workspaceReducer, start);
}

const loadedProject: WorkspaceAction = {
  type: "project/loaded",
  project: {
    id: "p1",
    name: "demo",
    kind: "memory",
    persistence: "browser-memory",
    readOnly: false,
    skippedEntries: 0,
    truncated: false,
  },
  entries: [
    { path: "a.py", type: "file" },
    { path: "b.ts", type: "file" },
    { path: "c.md", type: "file" },
  ],
};

function openLoaded(path: string, content: string): WorkspaceAction[] {
  return [
    { type: "tab/opened", path },
    { type: "file/loading", path },
    { type: "file/loaded", path, content },
  ];
}

describe("workspaceReducer", () => {
  it("tracks unsaved changes until the file is saved", () => {
    let state = reduce([loadedProject, ...openLoaded("a.py", "x = 1\n")]);
    expect(isDirty(state.buffers["a.py"])).toBe(false);

    state = reduce([{ type: "file/edited", path: "a.py", content: "x = 2\n" }], state);
    expect(isDirty(state.buffers["a.py"])).toBe(true);

    state = reduce(
      [
        { type: "file/saving", path: "a.py" },
        { type: "file/saved", path: "a.py", content: "x = 2\n" },
      ],
      state,
    );
    expect(isDirty(state.buffers["a.py"])).toBe(false);
    expect(state.buffers["a.py"].savedContent).toBe("x = 2\n");
  });

  it("stays dirty when edits happen while a save is in flight", () => {
    const state = reduce([
      loadedProject,
      ...openLoaded("a.py", "v1"),
      { type: "file/edited", path: "a.py", content: "v2" },
      { type: "file/saving", path: "a.py" },
      { type: "file/edited", path: "a.py", content: "v3" },
      { type: "file/saved", path: "a.py", content: "v2" },
    ]);
    expect(state.buffers["a.py"].content).toBe("v3");
    expect(isDirty(state.buffers["a.py"])).toBe(true);
  });

  it("preserves each file's content when switching tabs", () => {
    const state = reduce([
      loadedProject,
      ...openLoaded("a.py", "python"),
      ...openLoaded("b.ts", "typescript"),
      { type: "file/edited", path: "a.py", content: "python edited" },
      { type: "tab/activated", path: "a.py" },
    ]);
    expect(state.activePath).toBe("a.py");
    expect(state.openPaths).toEqual(["a.py", "b.ts"]);
    expect(state.buffers["a.py"].content).toBe("python edited");
    expect(state.buffers["b.ts"].content).toBe("typescript");
  });

  it("does not duplicate tabs when a file is opened twice", () => {
    const state = reduce([
      loadedProject,
      { type: "tab/opened", path: "a.py" },
      { type: "tab/opened", path: "a.py" },
    ]);
    expect(state.openPaths).toEqual(["a.py"]);
  });

  it("activates the neighbouring tab when the active tab closes and drops its buffer", () => {
    const state = reduce([
      loadedProject,
      ...openLoaded("a.py", "1"),
      ...openLoaded("b.ts", "2"),
      ...openLoaded("c.md", "3"),
      { type: "tab/activated", path: "b.ts" },
      { type: "tab/closed", path: "b.ts" },
    ]);
    expect(state.openPaths).toEqual(["a.py", "c.md"]);
    expect(state.activePath).toBe("c.md");
    expect(state.buffers["b.ts"]).toBeUndefined();

    const last = reduce(
      [
        { type: "tab/closed", path: "c.md" },
        { type: "tab/closed", path: "a.py" },
      ],
      state,
    );
    expect(last.activePath).toBeNull();
  });

  it("adds created files and their missing parent folders", () => {
    const state = reduce([loadedProject, { type: "file/created", path: "src/pkg/new.py" }]);
    const paths = state.entries.map((entry) => `${entry.type}:${entry.path}`);
    expect(paths).toEqual(
      expect.arrayContaining(["folder:src", "folder:src/pkg", "file:src/pkg/new.py"]),
    );
    expect(state.buffers["src/pkg/new.py"]).toMatchObject({
      status: "ready",
      content: "",
      savedContent: "",
    });
  });

  it("replaces and clears diagnostics per source and file", () => {
    const diagnostic: Diagnostic = {
      id: "1",
      severity: "error",
      category: "syntax",
      message: "Unexpected token",
      file: "b.ts",
      line: 1,
      column: 5,
      endLine: 1,
      endColumn: 6,
      source: "typescript",
      fixable: false,
      unnecessary: false,
    };
    let state = reduce([
      loadedProject,
      { type: "diagnostics/replaced", source: "editor", path: "b.ts", diagnostics: [diagnostic] },
    ]);
    expect(state.diagnostics.editor["b.ts"]).toEqual([diagnostic]);

    state = reduce(
      [{ type: "diagnostics/replaced", source: "editor", path: "b.ts", diagnostics: [] }],
      state,
    );
    expect(state.diagnostics.editor["b.ts"]).toBeUndefined();
  });

  it("resets project state but keeps editor settings when another project loads", () => {
    const state = reduce([
      { type: "settings/changed", settings: { fontSize: 18 } },
      loadedProject,
      ...openLoaded("a.py", "1"),
      { type: "project/loading" },
    ]);
    expect(state.projectStatus).toBe("loading");
    expect(state.openPaths).toEqual([]);
    expect(state.buffers).toEqual({});
    expect(state.editorSettings.fontSize).toBe(18);
  });
});
