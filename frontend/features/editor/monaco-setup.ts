import { loader } from "@monaco-editor/react";
import type * as MonacoModule from "monaco-editor";
import type { editor } from "monaco-editor";

import type { Diagnostic, DiagnosticSeverity } from "@/types/diagnostics";

/** Monaco is served from /public/monaco (copied from node_modules by scripts/copy-monaco.mjs). */
loader.config({ paths: { vs: "/monaco/vs" } });

/**
 * The Monaco namespace type. (@monaco-editor/react's own `Monaco` type resolves
 * to `any` with monaco-editor 0.57's exports map, which would disable checking.)
 */
export type Monaco = typeof MonacoModule;

export const THEME_NAME = "codewalk-dark";

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

  // Semantic checking needs the whole project's types and dependencies, which
  // the editor does not have (it would flag every import). Syntax checking is
  // self-contained and stays on. Project-aware analysis comes from the backend.
  const ts = monaco.typescript;
  for (const defaults of [ts.typescriptDefaults, ts.javascriptDefaults]) {
    defaults.setDiagnosticsOptions({ noSemanticValidation: true, noSyntaxValidation: false });
    defaults.setCompilerOptions({
      target: ts.ScriptTarget.ESNext,
      module: ts.ModuleKind.ESNext,
      jsx: ts.JsxEmit.ReactJSX,
      allowJs: true,
      allowNonTsExtensions: true,
    });
  }
}

/** Editor models are namespaced by project instance so same-named files never collide. */
export function modelUri(projectId: string, path: string): string {
  return `file:///${projectId}/${path.split("/").map(encodeURIComponent).join("/")}`;
}

/** Inverse of `modelUri` using a model URI's decoded path; null for models of other projects. */
export function pathFromModelUri(projectId: string, uriPath: string): string | null {
  const prefix = `/${projectId}/`;
  return uriPath.startsWith(prefix) ? uriPath.slice(prefix.length) : null;
}

function severityFromMarker(monaco: Monaco, severity: number): DiagnosticSeverity {
  switch (severity) {
    case monaco.MarkerSeverity.Error:
      return "error";
    case monaco.MarkerSeverity.Warning:
      return "warning";
    case monaco.MarkerSeverity.Info:
      return "info";
    default:
      return "hint";
  }
}

export function markersToDiagnostics(
  monaco: Monaco,
  path: string,
  markers: editor.IMarker[],
): Diagnostic[] {
  return markers.map((marker, index) => ({
    id: `${marker.owner}:${path}:${marker.startLineNumber}:${marker.startColumn}:${index}`,
    severity: severityFromMarker(monaco, marker.severity),
    message: marker.message,
    file: path,
    line: marker.startLineNumber,
    column: marker.startColumn,
    endLine: marker.endLineNumber,
    endColumn: marker.endColumn,
    source: marker.source ?? marker.owner,
    code: typeof marker.code === "string" ? marker.code : marker.code?.value,
  }));
}
