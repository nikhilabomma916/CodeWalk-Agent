// @vitest-environment jsdom
import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createInitialState, type WorkspaceState } from "@/features/workspace/state";
import { buildTree } from "@/lib/project-paths";
import type { ProjectEntry } from "@/types/project";

const renders = vi.hoisted(() => ({ files: 0 }));
const workspace = vi.hoisted(() => ({ value: null as unknown }));

vi.mock("./file-icon", () => ({
  FileIcon: () => {
    renders.files += 1;
    return null;
  },
  FolderIcon: () => null,
}));

vi.mock("@/features/workspace/workspace-context", () => ({
  useWorkspace: () => workspace.value,
}));

import { ProjectExplorer } from "./project-explorer";

const FILES = 400;
const actions = { openFile: vi.fn(), createFile: vi.fn() };

function stateWith(entries: ProjectEntry[], content: string): WorkspaceState {
  return {
    ...createInitialState(),
    projectStatus: "ready",
    project: {
      id: "p",
      name: "Big",
      kind: "server",
      persistence: "server",
      readOnly: false,
      skippedEntries: 0,
      truncated: false,
    },
    entries,
    activePath: "src/f0.py",
    openPaths: ["src/f0.py"],
    buffers: {
      "src/f0.py": {
        path: "src/f0.py",
        status: "ready",
        savedContent: "x = 0\n",
        content,
        saving: false,
      },
    },
  } as WorkspaceState;
}

describe("ProjectExplorer rendering", () => {
  beforeEach(() => {
    renders.files = 0;
  });

  it("does not re-render every row on each keystroke in the editor", () => {
    const entries: ProjectEntry[] = [
      { path: "src", type: "folder" },
      ...Array.from({ length: FILES }, (_, i) => ({ path: `src/f${i}.py`, type: "file" as const })),
    ];
    const tree = buildTree(entries, "Big");
    const set = (content: string) => {
      workspace.value = {
        state: stateWith(entries, content),
        tree,
        actions,
        canOpenDirectory: false,
      };
    };
    set("x = 0\n");
    const { rerender } = render(<ProjectExplorer />);
    expect(screen.getAllByRole("treeitem")).toHaveLength(FILES + 1); // the active file's folder is open
    expect(renders.files).toBe(FILES);

    // Typing: the first edit marks the file dirty (one row changes); later edits change no row.
    renders.files = 0;
    for (const text of ["x = 1\n", "x = 12\n", "x = 123\n"]) {
      set(text);
      act(() => rerender(<ProjectExplorer />));
    }
    expect(renders.files).toBe(1);
  });
});
