import { loader } from "@monaco-editor/react";
import type * as MonacoModule from "monaco-editor";
import type { editor } from "monaco-editor";

import type { Theme } from "@/lib/theme";
import type { Diagnostic } from "@/types/diagnostics";

/** Monaco is served from /public/monaco (copied from node_modules by scripts/copy-monaco.mjs). */
loader.config({ paths: { vs: "/monaco/vs" } });

/**
 * The Monaco namespace type. (@monaco-editor/react's own `Monaco` type resolves
 * to `any` with monaco-editor 0.57's exports map, which would disable checking.)
 */
export type Monaco = typeof MonacoModule;

/** Monaco theme per app theme. Switching the `theme` prop only calls setTheme: no remount, no lost state. */
export const MONACO_THEMES: Record<Theme, string> = {
  dark: "codewalk-dark",
  light: "codewalk-light",
};

export function monacoTheme(theme: Theme): string {
  return MONACO_THEMES[theme];
}

/** Marker owner for diagnostics coming from the backend analysis engine. */
export const ANALYSIS_MARKER_OWNER = "codewalk-analysis";

// Monaco measures glyphs from this exact string, so it cannot be a CSS variable.
export const MONO_FONT_STACK =
  'ui-monospace, "Cascadia Code", "JetBrains Mono", "SF Mono", Menlo, Consolas, "Liberation Mono", monospace';

import { registerEditorAICodeActions } from "./editor-ai-actions";
import { registerInlineCompletions } from "./inline-completion-provider";

let configured = false;

/** One-time global Monaco configuration; safe to call on every mount. */
export function configureMonaco(monaco: Monaco): void {
  if (configured) return;
  configured = true;
  registerInlineCompletions(monaco);
  registerEditorAICodeActions(monaco);

  // Editor colours mirror the app tokens in globals.css (Monaco cannot read CSS variables).
  monaco.editor.defineTheme(MONACO_THEMES.dark, {
    base: "vs-dark",
    inherit: true,
    rules: [],
    colors: {
      "editor.background": "#131b36",
      "editor.lineHighlightBackground": "#182447",
      "editorGutter.background": "#131b36",
      "editorLineNumber.foreground": "#6f82a3",
      "editorLineNumber.activeForeground": "#b8c1d1",
      "editor.selectionBackground": "#43597c99",
      "editor.inactiveSelectionBackground": "#43597c55",
      "editorCursor.foreground": "#f5f7fa",
      "editorWidget.background": "#143559",
      "editorWidget.border": "#43597c",
      "minimap.background": "#131b36",
    },
  });
  monaco.editor.defineTheme(MONACO_THEMES.light, {
    base: "vs",
    inherit: true,
    rules: [],
    colors: {
      "editor.background": "#ffffff",
      "editor.lineHighlightBackground": "#fafaf8",
      "editor.lineHighlightBorder": "#f0f0ec",
      "editorGutter.background": "#ffffff",
      "editorLineNumber.foreground": "#9a9a9a",
      "editorLineNumber.activeForeground": "#242424",
      "editor.selectionBackground": "#ffd5c899",
      "editor.inactiveSelectionBackground": "#ffe6de99",
      "editorCursor.foreground": "#0b0b0b",
      "editorWidget.background": "#ffffff",
      "editorWidget.border": "#eaeaea",
      "minimap.background": "#ffffff",
    },
  });

  // The backend analysis engine is the single source of diagnostics (Problems
  // panel and markers), so Monaco's own validators are turned off to avoid
  // duplicate or conflicting reports. Language features (completion, hover,
  // formatting) stay enabled.
  const ts = monaco.typescript;
  for (const defaults of [ts.typescriptDefaults, ts.javascriptDefaults]) {
    defaults.setDiagnosticsOptions({ noSemanticValidation: true, noSyntaxValidation: true });
    defaults.setCompilerOptions({
      target: ts.ScriptTarget.ESNext,
      module: ts.ModuleKind.ESNext,
      jsx: ts.JsxEmit.ReactJSX,
      allowJs: true,
      allowNonTsExtensions: true,
    });
  }
  monaco.json.jsonDefaults.setDiagnosticsOptions({ validate: false });
  for (const defaults of [
    monaco.css.cssDefaults,
    monaco.css.scssDefaults,
    monaco.css.lessDefaults,
  ]) {
    defaults.setOptions({ validate: false });
  }
}

/** Editor models are namespaced by project instance so same-named files never collide. */
export function modelUri(projectId: string, path: string): string {
  return `file:///${projectId}/${path.split("/").map(encodeURIComponent).join("/")}`;
}

/** The project path of a model created with modelUri, or null for another project's model. */
export function pathFromModelUri(projectId: string, uri: string): string | null {
  const prefix = `file:///${projectId}/`;
  if (!uri.startsWith(prefix)) return null;
  try {
    return uri.slice(prefix.length).split("/").map(decodeURIComponent).join("/");
  } catch {
    return null;
  }
}

export function toMarkers(
  monaco: Monaco,
  diagnostics: readonly Diagnostic[],
): editor.IMarkerData[] {
  const severity = {
    error: monaco.MarkerSeverity.Error,
    warning: monaco.MarkerSeverity.Warning,
    information: monaco.MarkerSeverity.Info,
    suggestion: monaco.MarkerSeverity.Hint,
  } as const;
  return diagnostics.map((diagnostic) => ({
    severity: severity[diagnostic.severity],
    message: diagnostic.message,
    source: diagnostic.source,
    code: diagnostic.documentationUrl
      ? { value: diagnostic.code ?? "", target: monaco.Uri.parse(diagnostic.documentationUrl) }
      : diagnostic.code,
    startLineNumber: diagnostic.line,
    startColumn: diagnostic.column,
    endLineNumber: diagnostic.endLine,
    endColumn: diagnostic.endColumn,
    tags: diagnostic.unnecessary ? [monaco.MarkerTag.Unnecessary] : undefined,
  }));
}
