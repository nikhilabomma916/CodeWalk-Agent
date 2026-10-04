import { ancestorPaths } from "@/lib/project-paths";
import { isApiError } from "@/services/api/errors";
import {
  createCodeFile,
  createFile,
  getFileContent,
  listFiles,
  updateFileContent,
  type ServerFile,
  type ServerProject,
} from "@/services/api/projects";
import type { ProjectEntry, ProjectPath } from "@/types/project";

import { SourceError, type ProjectSource, type SourceListing } from "./types";

function toSourceError(error: unknown, path: string): SourceError {
  if (error instanceof SourceError) return error;
  if (isApiError(error)) {
    if (error.status === 404)
      return new SourceError("not-found", `${path} no longer exists on the server.`);
    if (error.code === "file_exists") return new SourceError("exists", `${path} already exists.`);
    if (error.code === "project_read_only") return new SourceError("read-only", error.message);
    if (error.code === "invalid_file_name" || error.code === "unsupported_file_type")
      return new SourceError("invalid", error.message);
    if (error.status === 413) return new SourceError("too-large", error.message);
    return new SourceError("io", `${error.message} (${path})`, { cause: error });
  }
  return new SourceError("io", `Could not access ${path} on the server.`, { cause: error });
}

/** A project stored by the backend (PostgreSQL). Save sends the content to the server. */
export class ServerProjectSource implements ProjectSource {
  readonly kind = "server";
  readonly persistence = "server";
  readonly name: string;
  readonly readOnly: boolean;
  readonly serverProjectId: string;
  readonly rootPath?: string;
  private readonly fileIds = new Map<ProjectPath, string>();

  constructor(project: ServerProject) {
    this.name = project.name;
    this.readOnly = project.read_only;
    this.serverProjectId = project.id;
    this.rootPath = project.root_path ?? undefined;
  }

  private remember(file: ServerFile): void {
    this.fileIds.set(file.path, file.id);
  }

  async list(): Promise<SourceListing> {
    let files: ServerFile[];
    try {
      files = await listFiles(this.serverProjectId);
    } catch (error) {
      throw toSourceError(error, this.name);
    }
    this.fileIds.clear();
    files.forEach((file) => this.remember(file));
    const folders = new Set<ProjectPath>();
    for (const file of files) ancestorPaths(file.path).forEach((folder) => folders.add(folder));
    const entries: ProjectEntry[] = [
      ...[...folders].map((path) => ({ path, type: "folder" as const })),
      ...files.map((file) => ({ path: file.path, type: "file" as const, size: file.size })),
    ];
    return { entries, skipped: 0, truncated: false };
  }

  private fileId(path: ProjectPath): string {
    const id = this.fileIds.get(path);
    if (!id) throw new SourceError("not-found", `${path} is not on the server.`);
    return id;
  }

  async read(path: ProjectPath): Promise<string> {
    try {
      const content = await getFileContent(this.serverProjectId, this.fileId(path));
      if (content === null) {
        throw new SourceError(
          "binary",
          `${path} is binary or too large; its content is not stored.`,
        );
      }
      return content;
    } catch (error) {
      throw toSourceError(error, path);
    }
  }

  async write(path: ProjectPath, content: string): Promise<void> {
    if (this.readOnly) throw new SourceError("read-only", "This project is read-only.");
    try {
      this.remember(await updateFileContent(this.serverProjectId, this.fileId(path), content));
    } catch (error) {
      throw toSourceError(error, path);
    }
  }

  async createFile(path: ProjectPath): Promise<void> {
    if (this.readOnly) throw new SourceError("read-only", "This project is read-only.");
    try {
      this.remember(await createFile(this.serverProjectId, path, ""));
    } catch (error) {
      throw toSourceError(error, path);
    }
  }

  async createCodeFile(name: string): Promise<void> {
    if (this.readOnly) throw new SourceError("read-only", "This project is read-only.");
    try {
      this.remember(await createCodeFile(this.serverProjectId, name));
    } catch (error) {
      throw toSourceError(error, name);
    }
  }
}
