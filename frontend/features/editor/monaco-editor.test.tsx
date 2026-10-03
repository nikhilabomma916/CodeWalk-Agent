// @vitest-environment jsdom
import { render, waitFor } from "@testing-library/react";
import { useEffect } from "react";
import { describe, expect, it, vi } from "vitest";

import { DEFAULT_EDITOR_SETTINGS, type RevealRequest } from "@/features/workspace/state";

import MonacoEditor, { type MonacoEditorProps } from "./monaco-editor";

/**
 * Monaco needs a real browser. The stub mounts a fake editor instance asynchronously, like the real
 * component does after loading, and records where the caret was placed.
 */
const positions: { lineNumber: number; column: number }[] = [];

vi.mock("@monaco-editor/react", () => ({
  loader: { config: () => undefined, init: () => Promise.resolve({}) },
  default: function EditorStub(props: { onMount?: (instance: unknown, monaco: unknown) => void }) {
    useEffect(() => {
      const timer = setTimeout(() => {
        const instance = {
          addCommand: () => undefined,
          getPosition: () => ({ lineNumber: 1, column: 1 }),
          getModel: () => null,
          getSelections: () => [],
          getSelection: () => null,
          onDidChangeCursorSelection: () => undefined,
          onDidChangeModel: () => undefined,
          setPosition: (position: { lineNumber: number; column: number }) =>
            positions.push(position),
          revealPositionInCenter: () => undefined,
          focus: () => undefined,
        };
        const monaco = {
          KeyMod: { CtrlCmd: 2048 },
          KeyCode: { KeyS: 49 },
          editor: { getModels: () => [], getModel: () => null, setModelMarkers: () => undefined },
          Uri: { parse: (value: string) => value },
        };
        props.onMount?.(instance, monaco);
      }, 10);
      return () => clearTimeout(timer);
      // Mount once, like Monaco.
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);
    return <div data-testid="editor" />;
  },
}));

function props(reveal: RevealRequest | null): MonacoEditorProps {
  return {
    projectId: "p1",
    path: "src/auth/service.py",
    initialContent: "x = 1\n",
    language: "python",
    settings: DEFAULT_EDITOR_SETTINGS,
    readOnly: false,
    openPaths: ["src/auth/service.py"],
    diagnostics: {},
    reveal,
    onChange: () => undefined,
    onSave: () => undefined,
    onCursor: () => undefined,
    onReady: () => undefined,
  };
}

describe("MonacoEditor reveal", () => {
  it("applies a reveal requested before the editor existed (search result with no file open)", async () => {
    positions.length = 0;
    const reveal = { path: "src/auth/service.py", line: 8, column: 5, nonce: 101 };
    const { unmount } = render(<MonacoEditor {...props(reveal)} />);
    await waitFor(() => expect(positions).toEqual([{ lineNumber: 8, column: 5 }]));

    // The same request is not applied again when the editor remounts later.
    unmount();
    render(<MonacoEditor {...props(reveal)} />);
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(positions).toHaveLength(1);
  });

  it("applies new reveals after mount, and ignores reveals for other files", async () => {
    positions.length = 0;
    const { rerender } = render(<MonacoEditor {...props(null)} />);
    await new Promise((resolve) => setTimeout(resolve, 30));
    rerender(<MonacoEditor {...props({ path: "other.py", line: 3, column: 1, nonce: 102 })} />);
    rerender(
      <MonacoEditor {...props({ path: "src/auth/service.py", line: 4, column: 2, nonce: 103 })} />,
    );
    await waitFor(() => expect(positions).toEqual([{ lineNumber: 4, column: 2 }]));
  });
});
