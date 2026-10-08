import { afterEach, describe, expect, it, vi } from "vitest";

import {
  addSelectionActions,
  editorAIHandler,
  registerEditorAICodeActions,
  SELECTION_ACTIONS,
} from "./editor-ai-actions";
import type { Monaco } from "./monaco-setup";

afterEach(() => {
  editorAIHandler.current = null;
});

describe("Editor AI actions", () => {
  it("offers Explain and Suggest fix for each problem under the cursor, and runs them", () => {
    const commands = new Map<string, (...args: unknown[]) => void>();
    let provider: {
      provideCodeActions(model: unknown, range: unknown, context: unknown): { actions: unknown[] };
    } | null = null;
    const monaco = {
      editor: {
        registerCommand: (id: string, run: (...args: unknown[]) => void) => {
          commands.set(id, run);
          return { dispose() {} };
        },
      },
      languages: {
        registerCodeActionProvider: (_selector: unknown, p: typeof provider) => {
          provider = p;
          return { dispose() {} };
        },
      },
    } as unknown as Monaco;
    registerEditorAICodeActions(monaco);
    const handler = vi.fn();
    editorAIHandler.current = handler;
    const model = { uri: { toString: () => "file:///p1/app/main.py" } };
    const marker = {
      startLineNumber: 5,
      startColumn: 31,
      endLineNumber: 5,
      endColumn: 36,
      message: "Undefined name `total`",
      severity: 8,
    };
    const result = provider!.provideCodeActions(model, {}, { markers: [marker] }) as {
      actions: { title: string; command: { id: string; arguments: unknown[] } }[];
    };
    expect(result.actions.map((a) => a.title)).toEqual([
      "Explain with AI: Undefined name `total`",
      "Suggest fix with AI: Undefined name `total`",
    ]);
    const fix = result.actions[1].command;
    commands.get(fix.id)!(undefined, ...fix.arguments);
    expect(handler).toHaveBeenCalledWith({
      kind: "diagnostic",
      action: "fix",
      uri: "file:///p1/app/main.py",
      line: 5,
      column: 31,
      message: "Undefined name `total`",
    });
  });

  it("adds right-click AI actions that need a selection", () => {
    const added: { id: string; label: string; precondition: string; run(): void }[] = [];
    const instance = { addAction: (a: (typeof added)[number]) => added.push(a) };
    const run = vi.fn();
    addSelectionActions(instance as never, run);
    expect(added.map((a) => a.label)).toEqual(SELECTION_ACTIONS.map((a) => `AI: ${a.label}`));
    expect(new Set(added.map((a) => a.precondition))).toEqual(new Set(["editorHasSelection"]));
    added.find((a) => a.label === "AI: Generate tests")!.run();
    expect(run).toHaveBeenCalledWith({ kind: "selection", action: "tests" });
  });

  it("does nothing when no editor area is listening", () => {
    expect(editorAIHandler.current).toBeNull();
  });
});
