/**
 * AI actions inside the editor:
 * - a light bulb on a problem: "Explain with AI" and "Suggest fix with AI" (the fix opens the
 *   existing review: diff, then Apply or Reject; nothing changes without Apply);
 * - right-click on selected code: Explain, Fix, Optimize, Refactor, Generate tests, Add comments,
 *   Convert to another language (sent to the AI agent with the selection as the main context).
 */

import type { editor, IDisposable, languages } from "monaco-editor";

import type { AgentMode } from "@/services/api/agent";

import type { Monaco } from "./monaco-setup";

export type EditorAIRequest =
  | {
      kind: "diagnostic";
      action: "explain" | "fix";
      uri: string;
      line: number;
      column: number;
      message: string;
    }
  | { kind: "selection"; action: SelectionActionId };

/** Set by the editor area; the global Monaco commands call it. */
export const editorAIHandler: { current: ((request: EditorAIRequest) => void) | null } = {
  current: null,
};

export type SelectionActionId =
  "explain" | "fix" | "optimize" | "refactor" | "tests" | "comments" | "convert";

export interface SelectionAction {
  id: SelectionActionId;
  label: string;
  mode: AgentMode;
  /** The request sent to the agent; null when the developer completes it first (Convert). */
  message: string | null;
  draft?: string;
}

export const SELECTION_ACTIONS: SelectionAction[] = [
  {
    id: "explain",
    label: "Explain",
    mode: "assist",
    message: "Explain the selected code step by step.",
  },
  {
    id: "fix",
    label: "Fix",
    mode: "assist",
    message: "Find and fix the problems in the selected code. Propose the change for review.",
  },
  {
    id: "optimize",
    label: "Optimize / improve performance",
    mode: "assist",
    message:
      "Improve the performance of the selected code without changing its behavior. Explain the gain and propose the change for review.",
  },
  {
    id: "refactor",
    label: "Refactor",
    mode: "refactor",
    message: "Refactor the selected code for readability without changing its behavior.",
  },
  {
    id: "tests",
    label: "Generate tests",
    mode: "tests",
    message: "Generate tests for the selected code.",
  },
  {
    id: "comments",
    label: "Add comments",
    mode: "docs",
    message: "Add clear comments and docstrings to the selected code.",
  },
  {
    id: "convert",
    label: "Convert to another language…",
    mode: "assist",
    message: null,
    draft: "Convert the selected code to ",
  },
];

const EXPLAIN_COMMAND = "codewalk.ai.explainProblem";
const FIX_COMMAND = "codewalk.ai.fixProblem";

let registered: IDisposable[] | null = null;

/** Global, once: the light-bulb actions on problems and their commands. */
export function registerEditorAICodeActions(monaco: Monaco): void {
  if (registered) return;
  const run =
    (action: "explain" | "fix") =>
    (_accessor: unknown, uri: string, line: number, column: number, message: string) =>
      editorAIHandler.current?.({ kind: "diagnostic", action, uri, line, column, message });
  registered = [
    monaco.editor.registerCommand(EXPLAIN_COMMAND, run("explain")),
    monaco.editor.registerCommand(FIX_COMMAND, run("fix")),
    monaco.languages.registerCodeActionProvider(
      { pattern: "**" },
      {
        provideCodeActions(model: editor.ITextModel, _range, context: languages.CodeActionContext) {
          if (!editorAIHandler.current) return { actions: [], dispose() {} };
          const actions: languages.CodeAction[] = [];
          for (const marker of context.markers.slice(0, 3)) {
            const args = [
              model.uri.toString(),
              marker.startLineNumber,
              marker.startColumn,
              marker.message,
            ];
            const short =
              marker.message.length > 50 ? `${marker.message.slice(0, 47)}…` : marker.message;
            actions.push(
              {
                title: `Explain with AI: ${short}`,
                kind: "quickfix",
                diagnostics: [marker],
                command: { id: EXPLAIN_COMMAND, title: "Explain with AI", arguments: args },
              },
              {
                title: `Suggest fix with AI: ${short}`,
                kind: "quickfix",
                diagnostics: [marker],
                command: { id: FIX_COMMAND, title: "Suggest fix with AI", arguments: args },
              },
            );
          }
          return { actions, dispose() {} };
        },
      },
    ),
  ];
}

/** Per editor: the right-click "AI" actions, shown when code is selected. */
export function addSelectionActions(
  instance: editor.IStandaloneCodeEditor,
  run: (request: EditorAIRequest) => void,
): void {
  SELECTION_ACTIONS.forEach((action, index) => {
    instance.addAction({
      id: `codewalk.ai.selection.${action.id}`,
      label: `AI: ${action.label}`,
      precondition: "editorHasSelection",
      contextMenuGroupId: "1_codewalk_ai",
      contextMenuOrder: index + 1,
      run: () => run({ kind: "selection", action: action.id }),
    });
  });
}
