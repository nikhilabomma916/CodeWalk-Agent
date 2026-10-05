import { z } from "zod";

import { apiClient, type ApiClient } from "./client";

/** Module 20: GitHub connection and repository import. Tokens never reach the browser. */

const statusSchema = z.object({
  configured: z.boolean(),
  connected: z.boolean(),
  login: z.string().nullable(),
  scopes: z.array(z.string()),
  private_repositories: z.boolean(),
  connected_at: z.string().nullable(),
});
export type GitHubStatus = z.infer<typeof statusSchema>;

const repositorySchema = z.object({
  id: z.number(),
  full_name: z.string(),
  owner: z.string(),
  name: z.string(),
  private: z.boolean(),
  default_branch: z.string(),
  description: z.string().nullable(),
  size_kb: z.number(),
  updated_at: z.string().nullable(),
});
export type GitHubRepository = z.infer<typeof repositorySchema>;

const repositoryPageSchema = z.object({
  items: z.array(repositorySchema),
  page: z.number(),
  has_more: z.boolean(),
});
const branchPageSchema = z.object({
  items: z.array(z.string()),
  page: z.number(),
  has_more: z.boolean(),
});

const importResultSchema = z.object({
  project_id: z.string(),
  project_name: z.string(),
  repository: z.string(),
  branch: z.string(),
  commit_sha: z.string(),
  files_imported: z.number(),
  files_skipped: z.number(),
  skipped_by_reason: z.record(z.string(), z.number()),
  skipped: z.array(z.object({ path: z.string(), reason: z.string() })),
  indexing: z.string(),
  indexed_files: z.number(),
});
export type GitHubImportResult = z.infer<typeof importResultSchema>;

/** The server allows up to 120 s for downloading and reading a repository, plus indexing. */
export const GITHUB_IMPORT_TIMEOUT_MS = 180_000;

export async function getGitHubStatus(client: ApiClient = apiClient): Promise<GitHubStatus> {
  return (await client.request("/github/status", { schema: statusSchema })).data;
}

/** Starts OAuth: returns GitHub's authorization URL for the browser to open. */
export async function startGitHubConnect(client: ApiClient = apiClient): Promise<string> {
  const schema = z.object({ authorize_url: z.string().url() });
  const { data } = await client.request("/github/connect", { method: "POST", schema });
  return data.authorize_url;
}

export async function disconnectGitHub(client: ApiClient = apiClient): Promise<void> {
  await client.request("/github/connection", { method: "DELETE", schema: z.undefined() });
}

export async function listGitHubRepositories(page = 1, client: ApiClient = apiClient) {
  return (
    await client.request(`/github/repositories?page=${page}`, { schema: repositoryPageSchema })
  ).data;
}

export async function listGitHubBranches(
  owner: string,
  repository: string,
  client: ApiClient = apiClient,
) {
  const path = `/github/repositories/${encodeURIComponent(owner)}/${encodeURIComponent(repository)}/branches`;
  return (await client.request(path, { schema: branchPageSchema })).data;
}

export async function importGitHubRepository(
  body: { owner: string; repository: string; branch: string; project_name?: string },
  client: ApiClient = apiClient,
): Promise<GitHubImportResult> {
  const { data } = await client.request("/github/import", {
    method: "POST",
    body,
    schema: importResultSchema,
    timeoutMs: GITHUB_IMPORT_TIMEOUT_MS,
  });
  return data;
}
