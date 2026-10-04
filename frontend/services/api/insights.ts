import { z } from "zod";

import { apiClient, type ApiClient } from "./client";

/** Module 17: deterministic project insights (no AI) and project memory. */

const location = z.object({
  file_path: z.string(),
  lines: z.array(z.number()),
  relationship: z.enum(["confirmed", "possible"]),
  evidence: z.string(),
  role: z.string().nullable(),
  chain: z.array(z.string()),
});
export type InsightLocation = z.infer<typeof location>;

const route = z.object({
  file_path: z.string(),
  line: z.number(),
  method: z.string(),
  path: z.string(),
});
export type ApiRoute = z.infer<typeof route>;

const architectureSchema = z.object({
  files: z.number(),
  languages: z.record(z.string(), z.number()),
  roles: z.record(z.string(), z.number()),
  components: z.array(
    z.object({
      name: z.string(),
      files: z.number(),
      symbols: z.number(),
      languages: z.record(z.string(), z.number()),
      roles: z.record(z.string(), z.number()),
    }),
  ),
  links: z.array(
    z.object({
      source: z.string(),
      target: z.string(),
      imports: z.number(),
      relationship: z.string(),
    }),
  ),
  entry_points: z.array(z.string()),
  api_routes: z.array(route),
  data_models: z.array(z.string()),
  tests: z.number(),
  truncated: z.boolean(),
  limitations: z.array(z.string()),
});
export type Architecture = z.infer<typeof architectureSchema>;

const impactSchema = z.object({
  file_path: z.string(),
  symbol: z.string().nullable(),
  definitions: z.array(location),
  same_file_references: z.array(z.number()),
  direct_dependents: z.array(location),
  indirect_dependents: z.array(location),
  possible_references: z.array(location),
  dependencies: z.array(z.string()),
  external_imports: z.array(z.string()),
  related_tests: z.array(location),
  related_api_routes: z.array(route),
  truncated: z.boolean(),
  limitations: z.array(z.string()),
});
export type Impact = z.infer<typeof impactSchema>;

export const MEMORY_KINDS = [
  "convention",
  "decision",
  "terminology",
  "constraint",
  "preference",
] as const;
export type MemoryKind = (typeof MEMORY_KINDS)[number];

const memoryItem = z.object({
  id: z.string(),
  kind: z.enum(MEMORY_KINDS),
  text: z.string(),
  created_at: z.string(),
});
export type MemoryItem = z.infer<typeof memoryItem>;
const memoryList = z.object({ items: z.array(memoryItem), limit: z.number() });
export type MemoryList = z.infer<typeof memoryList>;

const base = (projectId: string) => `/projects/${encodeURIComponent(projectId)}`;

export async function getArchitecture(
  projectId: string,
  client: ApiClient = apiClient,
  signal?: AbortSignal,
): Promise<Architecture> {
  return (
    await client.request(`${base(projectId)}/architecture`, { schema: architectureSchema, signal })
  ).data;
}

export async function getImpact(
  projectId: string,
  filePath: string,
  symbol: string | null,
  client: ApiClient = apiClient,
  signal?: AbortSignal,
): Promise<Impact> {
  const { data } = await client.request(`${base(projectId)}/impact`, {
    method: "POST",
    body: { file_path: filePath, symbol: symbol || null },
    schema: impactSchema,
    signal,
  });
  return data;
}

export async function listMemory(
  projectId: string,
  client: ApiClient = apiClient,
): Promise<MemoryList> {
  return (await client.request(`${base(projectId)}/memory`, { schema: memoryList })).data;
}

export async function addMemory(
  projectId: string,
  kind: MemoryKind,
  text: string,
  client: ApiClient = apiClient,
): Promise<MemoryItem> {
  const { data } = await client.request(`${base(projectId)}/memory`, {
    method: "POST",
    body: { kind, text },
    schema: memoryItem,
  });
  return data;
}

export async function deleteMemory(
  projectId: string,
  memoryId: string,
  client: ApiClient = apiClient,
): Promise<void> {
  await client.request(`${base(projectId)}/memory/${encodeURIComponent(memoryId)}`, {
    method: "DELETE",
    schema: z.undefined(),
  });
}
