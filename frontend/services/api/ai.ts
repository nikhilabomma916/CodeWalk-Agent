import { z } from "zod";

import type { Diagnostic } from "@/types/diagnostics";

import { apiClient, type ApiClient } from "./client";

/** AI calls can take a while (the provider reasons before answering). */
const AI_TIMEOUT_MS = 150_000;

export const AI_ANALYSIS_TYPES = [
  "general_review",
  "bug_detection",
  "quality_review",
  "security_review",
  "performance_review",
  "explain_code",
] as const;
export type AIAnalysisType = (typeof AI_ANALYSIS_TYPES)[number];

const confidence = z.enum(["low", "medium", "high"]);
export type Confidence = z.infer<typeof confidence>;

const statusSchema = z.object({
  enabled: z.boolean(),
  configured: z.boolean(),
  available: z.boolean(),
  provider: z.string().nullable(),
  model: z.string().nullable(),
  detail: z.string().nullable(),
  analysis_types: z.array(z.enum(AI_ANALYSIS_TYPES)),
});
export type AIStatus = z.infer<typeof statusSchema>;

const contextSchema = z.object({
  used: z.boolean(),
  files: z.array(z.string()),
  symbols: z.array(z.string()),
  snippet_count: z.number(),
  semantic_snippet_count: z.number().optional().default(0),
  truncated: z.boolean(),
});

const baseSchema = z.object({
  request_id: z.string(),
  provider: z.string(),
  model: z.string(),
  generated_at: z.string(),
  confidence,
  warnings: z.array(z.string()),
  context: contextSchema,
  record_id: z.string().nullable(),
});

const findingSchema = z.object({
  id: z.string(),
  severity: z.enum(["error", "warning", "info"]),
  category: z.string(),
  title: z.string(),
  description: z.string(),
  reasoning: z.string(),
  basis: z.enum(["observed", "inferred"]),
  file_path: z.string(),
  line: z.number().nullable(),
  column: z.number().nullable(),
  end_line: z.number().nullable(),
  end_column: z.number().nullable(),
  confidence,
  suggestion: z.string().nullable(),
  related_diagnostic_id: z.string().nullable(),
  metadata: z.record(z.string(), z.unknown()),
});
export type AIFinding = z.infer<typeof findingSchema>;

const analysisSchema = baseSchema.extend({
  analysis_type: z.enum(AI_ANALYSIS_TYPES),
  summary: z.string(),
  findings: z.array(findingSchema),
});
export type AIAnalysis = z.infer<typeof analysisSchema>;

const explanationSchema = baseSchema.extend({
  diagnostic_id: z.string(),
  problem: z.string(),
  explanation: z.string(),
  cause: z.string(),
  impact: z.string(),
  suggested_fix: z.string(),
  related_code_locations: z.array(
    z.object({ file_path: z.string(), line: z.number().nullable(), reason: z.string() }),
  ),
});
export type AIExplanation = z.infer<typeof explanationSchema>;

const fixSchema = baseSchema.extend({
  status: z.enum(["suggested", "no_suggestion"]),
  summary: z.string(),
  explanation: z.string(),
  file_path: z.string(),
  original_code: z.string(),
  original_hash: z.string(),
  suggested_code: z.string(),
  diff: z.string(),
  edits: z.array(
    z.object({
      file_path: z.string(),
      start_line: z.number(),
      start_column: z.number(),
      end_line: z.number(),
      end_column: z.number(),
      replacement_text: z.string(),
    }),
  ),
});
export type AIFixSuggestion = z.infer<typeof fixSchema>;

/** What every AI request carries: the open file (possibly unsaved) and its diagnostics. */
export interface AIFileInput {
  code: string;
  filePath: string;
  projectId?: string;
  diagnostics: readonly Diagnostic[];
}

/** Backend (snake_case) shape of a diagnostic. */
export function toBackendDiagnostic(diagnostic: Diagnostic) {
  return {
    id: diagnostic.id,
    severity: diagnostic.severity,
    message: diagnostic.message.slice(0, 2000),
    source: diagnostic.source.slice(0, 64),
    code: diagnostic.code ? diagnostic.code.slice(0, 64) : null,
    category: diagnostic.category,
    line: diagnostic.line,
    column: diagnostic.column,
    end_line: Math.max(diagnostic.endLine, diagnostic.line),
    end_column:
      diagnostic.endLine > diagnostic.line
        ? diagnostic.endColumn
        : Math.max(diagnostic.endColumn, diagnostic.column),
  };
}

function baseBody(input: AIFileInput) {
  return {
    code: input.code,
    file_path: input.filePath,
    project_id: input.projectId,
    diagnostics: input.diagnostics.slice(0, 200).map(toBackendDiagnostic),
  };
}

export async function getAIStatus(client: ApiClient = apiClient): Promise<AIStatus> {
  return (await client.request("/ai/status", { schema: statusSchema })).data;
}

const completionSchema = z.object({
  completion: z.string(),
  provider: z.string(),
  model: z.string().nullable(),
});

/** Inline completion: the text to insert at the cursor (empty when nothing fits). */
export async function completeCode(
  input: {
    filePath: string;
    language: string;
    prefix: string;
    suffix: string;
    mode: "auto" | "comment";
  },
  signal?: AbortSignal,
  client: ApiClient = apiClient,
): Promise<string> {
  const { data } = await client.request("/ai/complete", {
    method: "POST",
    body: {
      file_path: input.filePath,
      language: input.language,
      prefix: input.prefix,
      suffix: input.suffix,
      mode: input.mode,
    },
    schema: completionSchema,
    timeoutMs: 20_000,
    signal,
  });
  return data.completion;
}

export async function analyzeWithAI(
  input: AIFileInput & { analysisType: AIAnalysisType },
  client: ApiClient = apiClient,
  signal?: AbortSignal,
): Promise<AIAnalysis> {
  const { data } = await client.request("/ai/analyze", {
    method: "POST",
    body: { ...baseBody(input), analysis_type: input.analysisType },
    schema: analysisSchema,
    timeoutMs: AI_TIMEOUT_MS,
    signal,
  });
  return data;
}

export async function explainDiagnostic(
  input: AIFileInput & { diagnostic: Diagnostic },
  client: ApiClient = apiClient,
  signal?: AbortSignal,
): Promise<AIExplanation> {
  const { data } = await client.request("/ai/explain", {
    method: "POST",
    body: { ...baseBody(input), diagnostic: toBackendDiagnostic(input.diagnostic) },
    schema: explanationSchema,
    timeoutMs: AI_TIMEOUT_MS,
    signal,
  });
  return data;
}

export async function suggestFix(
  input: AIFileInput & { diagnostic?: Diagnostic; instruction?: string },
  client: ApiClient = apiClient,
  signal?: AbortSignal,
): Promise<AIFixSuggestion> {
  const { data } = await client.request("/ai/fix-suggestion", {
    method: "POST",
    body: {
      ...baseBody(input),
      diagnostic: input.diagnostic ? toBackendDiagnostic(input.diagnostic) : undefined,
      instruction: input.instruction,
    },
    schema: fixSchema,
    timeoutMs: AI_TIMEOUT_MS,
    signal,
  });
  return data;
}
