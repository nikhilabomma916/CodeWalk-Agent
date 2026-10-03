import { z } from "zod";

import { apiClient, type ApiClient } from "./client";

export const SYMBOL_KINDS = [
  "class",
  "function",
  "method",
  "interface",
  "type_alias",
  "enum",
  "variable",
] as const;
export type SymbolKind = (typeof SYMBOL_KINDS)[number];

/** deterministic (Module 9, default), semantic (embeddings), or hybrid (both, fused by rank). */
export const SEARCH_MODES = ["deterministic", "semantic", "hybrid"] as const;
export type SearchMode = (typeof SEARCH_MODES)[number];

const snippetSchema = z.object({
  file_path: z.string(),
  start_line: z.number(),
  end_line: z.number(),
  lines: z.array(z.string()),
  truncated: z.boolean(),
});

const resultSchema = z.object({
  file_path: z.string(),
  symbol_name: z.string().nullable(),
  symbol_type: z.enum(SYMBOL_KINDS).nullable(),
  qualified_name: z.string().nullable(),
  language: z.string(),
  line: z.number().nullable(),
  end_line: z.number().nullable(),
  column: z.number().nullable(),
  score: z.number(),
  score_details: z
    .object({ base: z.number(), coverage: z.number(), context_bonus: z.number() })
    .nullable(),
  match_type: z.string(),
  match_reason: z.string(),
  snippet: snippetSchema.nullable(),
  related_symbols: z.array(z.string()),
  semantic_similarity: z.number().nullable().optional(),
  fusion: z
    .object({
      rrf_score: z.number(),
      k: z.number(),
      deterministic_rank: z.number().nullable(),
      semantic_rank: z.number().nullable(),
    })
    .nullable()
    .optional(),
});
export type SearchResult = z.infer<typeof resultSchema>;

const responseSchema = z.object({
  query: z.string(),
  terms: z.array(z.string()),
  results: z.array(resultSchema),
  total: z.number(),
  truncated: z.boolean(),
  indexed_files: z.number(),
  ranking: z.string(),
  mode: z.enum(SEARCH_MODES).optional(),
  mode_used: z.enum(SEARCH_MODES).optional(),
  warnings: z.array(z.string()).optional().default([]),
});
export type SearchResponse = z.infer<typeof responseSchema>;

export interface SearchInput {
  query: string;
  language?: string;
  symbolType?: SymbolKind;
  currentFile?: string;
  limit?: number;
  mode?: SearchMode;
}

export async function searchProject(
  projectId: string,
  input: SearchInput,
  client: ApiClient = apiClient,
  signal?: AbortSignal,
): Promise<SearchResponse> {
  const { data } = await client.request(`/projects/${encodeURIComponent(projectId)}/search`, {
    method: "POST",
    body: {
      query: input.query,
      limit: input.limit ?? 50,
      current_file: input.currentFile,
      mode: input.mode && input.mode !== "deterministic" ? input.mode : undefined,
      filters: { language: input.language || undefined, symbol_type: input.symbolType },
    },
    schema: responseSchema,
    signal,
    timeoutMs: 30_000,
  });
  return data;
}
