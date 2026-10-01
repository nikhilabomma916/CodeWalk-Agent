export type DiagnosticSeverity = "error" | "warning" | "information" | "suggestion";

export type DiagnosticCategory = "syntax" | "lint" | "style" | "type" | "semantic";

/**
 * A single problem reported for a file, as produced by the backend analysis
 * engine. Line and column are 1-based; endColumn is exclusive.
 */
export interface Diagnostic {
  id: string;
  severity: DiagnosticSeverity;
  category: DiagnosticCategory;
  message: string;
  file: string;
  line: number;
  column: number;
  endLine: number;
  endColumn: number;
  /** Which analyzer reported it, e.g. "ruff" or "typescript". */
  source: string;
  code?: string;
  suggestedAction?: string;
  documentationUrl?: string;
  fixable: boolean;
  /** Code that is unused/unreachable (rendered faded in the editor). */
  unnecessary: boolean;
}

export const SEVERITY_ORDER: Record<DiagnosticSeverity, number> = {
  error: 0,
  warning: 1,
  information: 2,
  suggestion: 3,
};
