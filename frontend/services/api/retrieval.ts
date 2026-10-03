import { z } from "zod";

import { apiClient, type ApiClient } from "./client";

/** Indexing embeds many chunks through the provider; allow it time. */
const INDEX_TIMEOUT_MS = 300_000;

const statusSchema = z.object({
  enabled: z.boolean(),
  configured: z.boolean(),
  available: z.boolean(),
  provider: z.string().nullable(),
  model: z.string().nullable(),
  dimensions: z.number(),
  detail: z.string().nullable(),
});
export type RetrievalStatus = z.infer<typeof statusSchema>;

const indexStatusSchema = z.object({
  available: z.boolean(),
  model: z.string().nullable(),
  indexable_files: z.number(),
  indexed_files: z.number(),
  stale_files: z.number(),
  chunks: z.number(),
});
export type IndexStatus = z.infer<typeof indexStatusSchema>;

const indexRunSchema = z.object({
  files_indexed: z.number(),
  chunks_embedded: z.number(),
  chunks_reused: z.number(),
  tokens_used: z.number(),
  remaining_files: z.number(),
  status: indexStatusSchema,
});
export type IndexRun = z.infer<typeof indexRunSchema>;

/** Whether semantic retrieval is enabled and configured on the server (no provider call). */
export async function getRetrievalStatus(client: ApiClient = apiClient): Promise<RetrievalStatus> {
  return (await client.request("/rag/status", { schema: statusSchema })).data;
}

export async function getIndexStatus(
  projectId: string,
  client: ApiClient = apiClient,
  signal?: AbortSignal,
): Promise<IndexStatus> {
  const { data } = await client.request(`/projects/${encodeURIComponent(projectId)}/rag/index`, {
    schema: indexStatusSchema,
    signal,
  });
  return data;
}

/** Embeds new and changed files of the project (incremental; may need several runs). */
export async function indexProject(
  projectId: string,
  client: ApiClient = apiClient,
): Promise<IndexRun> {
  const { data } = await client.request(`/projects/${encodeURIComponent(projectId)}/rag/index`, {
    method: "POST",
    schema: indexRunSchema,
    timeoutMs: INDEX_TIMEOUT_MS,
  });
  return data;
}
