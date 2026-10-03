import { z } from "zod";

import type { Diagnostic } from "@/types/diagnostics";

import { apiClient, type ApiClient } from "./client";

/** Backend `Language` values (app/services/languages.py). */
export const BACKEND_LANGUAGES = [
  "python",
  "javascript",
  "javascriptreact",
  "typescript",
  "typescriptreact",
  "json",
  "html",
  "css",
  "sql",
  "markdown",
  "java",
  "c",
  "cpp",
  "scss",
  "yaml",
  "toml",
  "xml",
  "shell",
  "go",
  "rust",
  "csharp",
  "php",
  "ruby",
  "kotlin",
  "swift",
  "dockerfile",
  "plaintext",
  "unknown",
] as const;

export type BackendLanguage = (typeof BACKEND_LANGUAGES)[number];

const diagnosticSchema = z.object({
  id: z.string(),
  severity: z.enum(["error", "warning", "information", "suggestion"]),
  message: z.string(),
  source: z.string(),
  code: z.string().nullable(),
  category: z.enum(["syntax", "lint", "style", "type", "semantic"]),
  file_path: z.string().nullable(),
  line: z.number().int(),
  column: z.number().int(),
  end_line: z.number().int(),
  end_column: z.number().int(),
  suggestion: z.string().nullable(),
  documentation_url: z.string().nullable(),
  fixable: z.boolean(),
  metadata: z.record(z.string(), z.unknown()),
});

export const capabilitySchema = z.object({
  kind: z.enum(["syntax", "lint", "types", "semantic"]),
  status: z.enum(["performed", "skipped", "unavailable", "not_supported"]),
  analyzer: z.string().nullable(),
  detail: z.string().nullable(),
});

export type AnalysisCapability = z.infer<typeof capabilitySchema>;

const analysisResultSchema = z.object({
  file_path: z.string().nullable(),
  language: z.enum(BACKEND_LANGUAGES),
  success: z.boolean(),
  diagnostics: z.array(diagnosticSchema),
  capabilities: z.array(capabilitySchema),
  analyzers: z.array(z.object({ name: z.string(), version: z.string().nullable() })),
  errors: z.array(z.string()),
  analysis_duration_ms: z.number(),
  analyzed_at: z.string(),
});

export interface AnalysisOutcome {
  language: BackendLanguage;
  success: boolean;
  diagnostics: Diagnostic[];
  capabilities: AnalysisCapability[];
  errors: string[];
  durationMs: number;
}

export async function analyzeCode(
  request: { code: string; filePath: string; language?: BackendLanguage },
  options: { signal?: AbortSignal } = {},
  client: ApiClient = apiClient,
): Promise<AnalysisOutcome> {
  const { data } = await client.request("/analysis/code", {
    method: "POST",
    body: { code: request.code, file_path: request.filePath, language: request.language },
    schema: analysisResultSchema,
    signal: options.signal,
    timeoutMs: 20_000,
  });
  return {
    language: data.language,
    success: data.success,
    capabilities: data.capabilities,
    errors: data.errors,
    durationMs: data.analysis_duration_ms,
    diagnostics: data.diagnostics.map((d) => ({
      id: d.id,
      severity: d.severity,
      category: d.category,
      message: d.message,
      file: request.filePath,
      line: d.line,
      column: d.column,
      endLine: d.end_line,
      endColumn: d.end_column,
      source: d.source,
      code: d.code ?? undefined,
      suggestedAction: d.suggestion ?? undefined,
      documentationUrl: d.documentation_url ?? undefined,
      fixable: d.fixable,
      unnecessary: d.metadata.unnecessary === true,
    })),
  };
}
