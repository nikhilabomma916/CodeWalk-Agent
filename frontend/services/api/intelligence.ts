import { z } from "zod";

import { apiClient, type ApiClient } from "./client";
import { isApiError } from "./errors";

const symbolSchema = z.object({
  id: z.string(),
  name: z.string(),
  qualified_name: z.string(),
  kind: z.enum(["class", "function", "method", "interface", "type_alias", "enum", "variable"]),
  file_path: z.string(),
  line: z.number(),
  column: z.number(),
  end_line: z.number(),
  end_column: z.number(),
  parent: z.string().nullable(),
  signature: z.string().nullable(),
  is_async: z.boolean(),
  decorators: z.array(z.string()),
  parameters: z.array(z.string()),
  return_annotation: z.string().nullable(),
  exported: z.boolean().nullable(),
});

const importSchema = z.object({
  module: z.string(),
  names: z.array(z.string()),
  kind: z.string(),
  line: z.number(),
  level: z.number(),
  resolved_path: z.string().nullable(),
});

const fileSchema = z.object({
  path: z.string(),
  name: z.string(),
  extension: z.string(),
  language: z.string(),
  size: z.number(),
  line_count: z.number(),
  symbols: z.array(symbolSchema),
  imports: z.array(importSchema),
  exports: z.array(z.string()),
  structure_supported: z.boolean(),
  skipped_reason: z.string().nullable(),
});

const statisticsSchema = z.object({
  total_files: z.number(),
  total_directories: z.number(),
  total_lines: z.number(),
  total_bytes: z.number(),
  languages: z.array(
    z.object({ language: z.string(), files: z.number(), lines: z.number(), bytes: z.number() }),
  ),
  largest_files: z.array(z.object({ path: z.string(), size: z.number(), line_count: z.number() })),
  symbol_counts: z.record(z.string(), z.number()),
  total_symbols: z.number(),
  total_imports: z.number(),
  internal_imports: z.number(),
  external_imports: z.number(),
  analysis_errors: z.number(),
  skipped_files: z.number(),
});

export const projectIntelligenceSchema = z.object({
  project: z.object({
    id: z.string().nullable(),
    name: z.string(),
    root_path: z.string().nullable(),
  }),
  files: z.array(fileSchema),
  directories: z.array(z.string()),
  relationships: z.array(
    z.object({
      source: z.string(),
      target: z.string(),
      kind: z.enum(["imports", "defines", "contains"]),
      target_kind: z.enum(["file", "module", "symbol"]),
      line: z.number().nullable(),
    }),
  ),
  statistics: statisticsSchema,
  errors: z.array(z.object({ path: z.string(), stage: z.string(), message: z.string() })),
  analysis_id: z.string().nullable(),
  analyzed_at: z.string(),
  duration_ms: z.number(),
  sync: z
    .object({
      created: z.number(),
      updated: z.number(),
      deleted: z.number(),
      unchanged: z.number(),
    })
    .nullable(),
});

export type ProjectIntelligence = z.infer<typeof projectIntelligenceSchema>;
export type IntelligenceSymbol = z.infer<typeof symbolSchema>;

export async function analyzeProject(
  projectId: string,
  client: ApiClient = apiClient,
): Promise<ProjectIntelligence> {
  const { data } = await client.request(`/projects/${encodeURIComponent(projectId)}/analyze`, {
    method: "POST",
    schema: projectIntelligenceSchema,
    timeoutMs: 120_000,
  });
  return data;
}

/** Latest stored intelligence, or null when the project was never analyzed. */
export async function getProjectIntelligence(
  projectId: string,
  client: ApiClient = apiClient,
): Promise<ProjectIntelligence | null> {
  try {
    const { data } = await client.request(
      `/projects/${encodeURIComponent(projectId)}/intelligence`,
      {
        schema: projectIntelligenceSchema,
        timeoutMs: 60_000,
      },
    );
    return data;
  } catch (error) {
    if (isApiError(error) && error.code === "not_analyzed") return null;
    throw error;
  }
}
