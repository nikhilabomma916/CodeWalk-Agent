import { z } from "zod";

import { apiClient, type ApiClient } from "./client";

const projectSchema = z.object({
  id: z.string(),
  name: z.string(),
  description: z.string().nullable(),
  root_path: z.string().nullable(),
  read_only: z.boolean(),
  created_at: z.string(),
  updated_at: z.string(),
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

export async function listProjects(client: ApiClient = apiClient): Promise<ServerProject[]> {
  const { data } = await client.request("/projects?limit=200", { schema: page(projectSchema) });
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
  input: { name: string; rootPath?: string },
  client: ApiClient = apiClient,
): Promise<ServerProject> {
  const { data } = await client.request("/projects", {
    method: "POST",
    body: { name: input.name, root_path: input.rootPath },
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
