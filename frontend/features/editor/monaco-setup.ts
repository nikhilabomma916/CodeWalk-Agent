import { loader } from "@monaco-editor/react";
import type * as MonacoModule from "monaco-editor";
import type { editor } from "monaco-editor";

import type { Diagnostic } from "@/types/diagnostics";

/** Monaco is served from /public/monaco (copied from node_modules by scripts/copy-monaco.mjs). */
loader.config({ paths: { vs: "/monaco/vs" } });

/**
 * The Monaco namespace type. (@monaco-editor/react's own `Monaco` type resolves
 * to `any` with monaco-editor 0.57's exports map, which would disable checking.)
 */
export type Monaco = typeof MonacoModule;

export const THEME_NAME = "codewalk-dark";

/** Marker owner for diagnostics coming from the backend analysis engine. */
export const ANALYSIS_MARKER_OWNER = "codewalk-analysis";

// Monaco measures glyphs from this exact string, so it cannot be a CSS variable.
export const MONO_FONT_STACK =
  'ui-monospace, "Cascadia Code", "JetBrains Mono", "SF Mono", Menlo, Consolas, "Liberation Mono", monospace';

let configured = false;

/** One-time global Monaco configuration; safe to call on every mount. */
export function configureMonaco(monaco: Monaco): void {
  if (configured) return;
  configured = true;

  monaco.editor.defineTheme(THEME_NAME, {
    base: "vs-dark",
    inherit: true,
    rules: [],
    colors: {
      "editor.background": "#16181d",
      "editor.lineHighlightBackground": "#1f222a",
      "editorGutter.background": "#16181d",
      "editorLineNumber.foreground": "#4b5263",
      "editorLineNumber.activeForeground": "#aeb4c0",
      "minimap.background": "#16181d",
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
