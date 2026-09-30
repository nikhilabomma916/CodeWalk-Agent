export type DiagnosticSeverity = "error" | "warning" | "info" | "hint";

/**
 * A single problem reported for a file. Producers (the editor's built-in
 * syntax checker today; the backend analysis engine later) all emit this shape.
 * Line and column are 1-based.
 */
export interface Diagnostic {
  id: string;
  severity: DiagnosticSeverity;
  message: string;
  file: string;
  line: number;
  column: number;
  endLine?: number;
  endColumn?: number;
  /** Which producer reported it, e.g. "typescript" or "ruff". */
  source: string;
  code?: string;
  suggestedAction?: string;
}

export const SEVERITY_ORDER: Record<DiagnosticSeverity, number> = {
  error: 0,
  warning: 1,
  info: 2,
  hint: 3,
};
