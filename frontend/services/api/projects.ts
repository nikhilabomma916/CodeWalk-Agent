import { z } from "zod";

import { apiClient, type ApiClient } from "./client";

/** Computed by the backend from stored files and analyses. */
const projectStatsSchema = z.object({
  file_count: z.number(),
  total_bytes: z.number(),
  total_lines: z.number(),
  languages: z.array(z.object({ language: z.string(), files: z.number() })),
  last_analyzed_at: z.string().nullable(),
});

const projectSchema = z.object({
  id: z.string(),
  name: z.string(),
  description: z.string().nullable(),
  root_path: z.string().nullable(),
  read_only: z.boolean(),
  /** "upload": a folder uploaded from the developer's computer (Uploads area, analyzed read-only). */
  origin: z.enum(["workspace", "upload"]).default("workspace"),
  created_at: z.string(),
  updated_at: z.string(),
  stats: projectStatsSchema,
});

export type ServerProject = z.infer<typeof projectSchema>;

const page = <T extends z.ZodType>(item: T) =>
  z.object({ items: z.array(item), total: z.number(), limit: z.number(), offset: z.number() });

const fileMetadataSchema = z.object({
  id: z.string(),
  project_id: z.string(),
  path: z.string(),
  name: z.string(),
  language: z.string(),
  size: z.number(),
  line_count: z.number(),
  content_hash: z.string().nullable(),
  has_content: z.boolean(),
  created_at: z.string(),
  updated_at: z.string(),
});

export type ServerFile = z.infer<typeof fileMetadataSchema>;

const fileDetailSchema = fileMetadataSchema.extend({ content: z.string().nullable() });
const fileSaveSchema = z.object({ file: fileDetailSchema, analysis: z.unknown().nullable() });

const workspaceSchema = z.object({ enabled: z.boolean(), folders: z.array(z.string()) });
export type WorkspaceFolders = z.infer<typeof workspaceSchema>;

const noContent = z.undefined();

export type ProjectOrigin = ServerProject["origin"];

/** The user's projects; `origin` limits the list to workspace projects or uploaded folders. */
export async function listProjects(
  options: { origin?: ProjectOrigin } = {},
  client: ApiClient = apiClient,
): Promise<ServerProject[]> {
  const query = options.origin ? `&origin=${options.origin}` : "";
  const { data } = await client.request(`/projects?limit=200${query}`, {
    schema: page(projectSchema),
  });
  return data.items;
}

export async function getProject(
  id: string,
  client: ApiClient = apiClient,
): Promise<ServerProject> {
  return (await client.request(`/projects/${encodeURIComponent(id)}`, { schema: projectSchema }))
    .data;
}

export async function createProject(
  input: { name: string; description?: string; rootPath?: string; origin?: ProjectOrigin },
  client: ApiClient = apiClient,
): Promise<ServerProject> {
  const { data } = await client.request("/projects", {
    method: "POST",
    body: {
      name: input.name,
      description: input.description || undefined,
      root_path: input.rootPath,
      origin: input.origin,
    },
    schema: projectSchema,
  });
  return data;
}

export async function updateProject(
  id: string,
  changes: { name?: string; description?: string | null },
  client: ApiClient = apiClient,
): Promise<ServerProject> {
  const { data } = await client.request(`/projects/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: changes,
    schema: projectSchema,
  });
  return data;
}

export async function deleteProject(id: string, client: ApiClient = apiClient): Promise<void> {
  await client.request(`/projects/${encodeURIComponent(id)}`, {
    method: "DELETE",
    schema: noContent,
  });
}

export async function getWorkspaceFolders(
  client: ApiClient = apiClient,
): Promise<WorkspaceFolders> {
  return (await client.request("/projects/workspace", { schema: workspaceSchema })).data;
}

/** All files of a project (metadata only), following pagination. */
export async function listFiles(
  projectId: string,
  client: ApiClient = apiClient,
): Promise<ServerFile[]> {
  const files: ServerFile[] = [];
  for (let offset = 0; ;) {
    const { data } = await client.request(
      `/projects/${encodeURIComponent(projectId)}/files?limit=5000&offset=${offset}`,
      { schema: page(fileMetadataSchema) },
    );
    files.push(...data.items);
    offset += data.items.length;
    if (data.items.length === 0 || offset >= data.total) return files;
  }
}

export async function getFileContent(
  projectId: string,
  fileId: string,
  client: ApiClient = apiClient,
): Promise<string | null> {
  const { data } = await client.request(
    `/projects/${encodeURIComponent(projectId)}/files/${encodeURIComponent(fileId)}`,
    { schema: fileDetailSchema },
  );
  return data.content;
}

export async function createFile(
  projectId: string,
  path: string,
  content: string,
  client: ApiClient = apiClient,
): Promise<ServerFile> {
  const { data } = await client.request(`/projects/${encodeURIComponent(projectId)}/files`, {
    method: "POST",
    body: { path, content },
    schema: fileSaveSchema,
  });
  return data.file;
}

const importResultSchema = z.object({
  created: z.array(fileMetadataSchema),
  skipped: z.array(z.object({ path: z.string(), reason: z.string(), message: z.string() })),
});

export type ImportResult = z.infer<typeof importResultSchema>;

/** Uploads one batch (at most 100 files) of a local folder into a server project. */
export async function importFiles(
  projectId: string,
  files: { path: string; content: string }[],
  options: { signal?: AbortSignal } = {},
  client: ApiClient = apiClient,
): Promise<ImportResult> {
  const { data } = await client.request(`/projects/${encodeURIComponent(projectId)}/files/import`, {
    method: "POST",
    body: { files },
    schema: importResultSchema,
    signal: options.signal,
    timeoutMs: 120_000,
  });
  return data;
}

/** Coding "+ New File": an empty file at the project root, from a file name only. */
export async function createCodeFile(
  projectId: string,
  name: string,
  client: ApiClient = apiClient,
): Promise<ServerFile> {
  const { data } = await client.request(
    `/projects/${encodeURIComponent(projectId)}/files/code-file`,
    { method: "POST", body: { name }, schema: fileSaveSchema },
  );
  return data.file;
}

export async function updateFileContent(
  projectId: string,
  fileId: string,
  content: string,
  client: ApiClient = apiClient,
): Promise<ServerFile> {
  const { data } = await client.request(
    `/projects/${encodeURIComponent(projectId)}/files/${encodeURIComponent(fileId)}`,
    { method: "PATCH", body: { content }, schema: fileSaveSchema, timeoutMs: 30_000 },
  );
  return data.file;
}

const fileVersionSchema = z.object({
  version: z.number(),
  size: z.number(),
  line_count: z.number(),
  content_hash: z.string(),
  source: z.string(),
  author_id: z.string().nullable(),
  created_at: z.string(),
  content: z.string(),
});

export type FileVersion = z.infer<typeof fileVersionSchema>;

export async function getFileVersion(
  projectId: string,
  fileId: string,
  version: number,
  client: ApiClient = apiClient,
): Promise<FileVersion> {
  const { data } = await client.request(
    `/projects/${encodeURIComponent(projectId)}/files/${encodeURIComponent(fileId)}/versions/${version}`,
    { schema: fileVersionSchema },
  );
  return data;
}
