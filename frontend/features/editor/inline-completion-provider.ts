/**
 * Registers CodeWalk's AI ghost-text provider with Monaco (once). Monaco handles the display and the
 * keys: Tab accepts, Escape dismisses, Alt+[ / Alt+] show the previous/next suggestion; Ctrl+Space
 * asks explicitly (see monaco-editor.tsx). Nothing is inserted unless the developer accepts it.
 */

import type { IDisposable, editor, languages, Position, CancellationToken } from "monaco-editor";

import { completeCode } from "@/services/api/ai";

import {
  completionModeAt,
  InlineCompletionEngine,
  type CompletionStatus,
} from "./inline-completion";
import type { Monaco } from "./monaco-setup";

type Listener = () => void;

/** What the provider needs from React: whether to run, and the file path of a model. */
export const inlineCompletionConfig: {
  enabled: boolean;
  pathFor(uri: string): string | null;
} = {
  enabled: false,
  pathFor: () => null,
};

const listeners = new Set<Listener>();
let currentStatus: CompletionStatus = { state: "idle" };

export const completionEngine = new InlineCompletionEngine(
  (input, signal) => completeCode(input, signal),
  {
    onStatus(status) {
      currentStatus = status;
      listeners.forEach((listener) => listener());
    },
  },
);

/** For useSyncExternalStore: the status bar shows when completions are paused and why. */
export const completionStatusStore = {
  subscribe(listener: Listener) {
    listeners.add(listener);
    return () => listeners.delete(listener);
  },
  get: () => currentStatus,
};

const EMPTY: languages.InlineCompletions = { items: [] };

export function createInlineCompletionsProvider(
  monaco: Monaco,
  engine: Pick<InlineCompletionEngine, "complete"> = completionEngine,
): languages.InlineCompletionsProvider {
  return {
    async provideInlineCompletions(
      model: editor.ITextModel,
      position: Position,
      context: languages.InlineCompletionContext,
      token: CancellationToken,
    ) {
      if (!inlineCompletionConfig.enabled) return EMPTY;
      const filePath = inlineCompletionConfig.pathFor(model.uri.toString());
      if (!filePath) return EMPTY;
      const explicit =
        context.triggerKind === monaco.languages.InlineCompletionTriggerKind.Explicit;
      const line = model.getLineContent(position.lineNumber);
      const lineSuffix = line.slice(position.column - 1);
      const prefix = model.getValueInRange({
        startLineNumber: 1,
        startColumn: 1,
        endLineNumber: position.lineNumber,
        endColumn: position.column,
      });
      const mode = completionModeAt(prefix, lineSuffix, explicit);
      if (!mode) return EMPTY;
      const lastLine = model.getLineCount();
      const suffix = model.getValueInRange({
        startLineNumber: position.lineNumber,
        startColumn: position.column,
        endLineNumber: lastLine,
        endColumn: model.getLineMaxColumn(lastLine),
      });
      const version = model.getVersionId();
      const controller = new AbortController();
      const cancel = token.onCancellationRequested(() => controller.abort());
      try {
        let text = await engine.complete(
          { filePath, language: model.getLanguageId(), prefix, suffix, mode },
          { signal: controller.signal, explicit },
        );
        // Stale: the text changed while waiting (Monaco also re-asks on the next pause).
        if (!text || token.isCancellationRequested || model.getVersionId() !== version)
          return EMPTY;
        // Monaco shows multi-line ghost text only when nothing follows the cursor on its line.
        if (text.includes("\n") && lineSuffix.trim() !== "") text = text.split("\n")[0];
        if (!text) return EMPTY;
        return {
          items: [
            {
              insertText: text,
              range: new monaco.Range(
                position.lineNumber,
                position.column,
                position.lineNumber,
                position.column,
              ),
            },
          ],
        };
      } finally {
        cancel.dispose();
      }
    },
    disposeInlineCompletions() {},
  };
}

let registration: IDisposable | null = null;

/** Registers the provider for every language (once per page). */
export function registerInlineCompletions(monaco: Monaco): void {
  if (registration) return;
  registration = monaco.languages.registerInlineCompletionsProvider(
    { pattern: "**" },
    createInlineCompletionsProvider(monaco),
  );
}
