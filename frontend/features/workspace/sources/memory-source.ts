import { ancestorPaths } from "@/lib/project-paths";
import type { ProjectEntry, ProjectPath } from "@/types/project";

import { SourceError, type ProjectSource, type SourceListing } from "./types";

/** A new project that lives only in this browser tab. */
export class MemoryProjectSource implements ProjectSource {
  readonly kind = "memory";
  readonly persistence = "browser-memory";
  readonly readOnly = false;
  private readonly files = new Map<ProjectPath, string>();

  constructor(readonly name: string) {}

  async list(): Promise<SourceListing> {
    const folders = new Set<ProjectPath>();
    for (const path of this.files.keys())
      ancestorPaths(path).forEach((folder) => folders.add(folder));
    const entries: ProjectEntry[] = [
      ...[...folders].map((path) => ({ path, type: "folder" as const })),
      ...[...this.files.keys()].map((path) => ({ path, type: "file" as const })),
    ];
    return { entries, skipped: 0, truncated: false };
  }

  async read(path: ProjectPath): Promise<string> {
    const content = this.files.get(path);
    if (content === undefined) throw new SourceError("not-found", `${path} does not exist.`);
    return content;
  }

  async write(path: ProjectPath, content: string): Promise<void> {
    this.files.set(path, content);
  }

  async createFile(path: ProjectPath): Promise<void> {
    if (this.files.has(path)) throw new SourceError("exists", `${path} already exists.`);
    this.files.set(path, "");
  }
}
