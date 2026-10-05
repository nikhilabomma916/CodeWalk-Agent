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
    await this.createFileWithContent(path, "");
  }

  async createFileWithContent(path: ProjectPath, content: string): Promise<void> {
    if (this.files.has(path)) throw new SourceError("exists", `${path} already exists.`);
    this.files.set(path, content);
  }

  private under(path: ProjectPath): ProjectPath[] {
    const found = [...this.files.keys()].filter((p) => p === path || p.startsWith(`${path}/`));
    if (found.length === 0) throw new SourceError("not-found", `${path} does not exist.`);
    return found;
  }

  async renamePath(from: ProjectPath, to: ProjectPath): Promise<void> {
    if (from === to) return;
    if (to.startsWith(`${from}/`))
      throw new SourceError("invalid", "A folder cannot be moved into itself.");
    const moves = this.under(from).map((path) => [path, to + path.slice(from.length)] as const);
    const moving = new Set(moves.map(([path]) => path));
    for (const [, target] of moves)
      if (this.files.has(target) && !moving.has(target))
        throw new SourceError("exists", `${target} already exists.`);
    const contents = moves.map(([path, target]) => [target, this.files.get(path) ?? ""] as const);
    moves.forEach(([path]) => this.files.delete(path));
    contents.forEach(([target, content]) => this.files.set(target, content));
  }

  async deletePath(path: ProjectPath): Promise<void> {
    this.under(path).forEach((p) => this.files.delete(p));
  }
}
