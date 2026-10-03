import { ancestorPaths, isIgnoredPath } from "@/lib/project-paths";
import type { ProjectEntry, ProjectPath } from "@/types/project";

import { decodeTextFile } from "./decode";
import { MAX_PROJECT_ENTRIES, SourceError, type ProjectSource, type SourceListing } from "./types";

/**
 * A folder selected with `<input webkitdirectory>` (browsers without the File
 * System Access API). The original files cannot be written, so saved changes
 * are kept in this tab only.
 */
export class LocalSnapshotSource implements ProjectSource {
  readonly kind = "local-snapshot";
  readonly persistence = "browser-memory";
  readonly readOnly = false;
  private readonly originals = new Map<ProjectPath, File>();
  private readonly saved = new Map<ProjectPath, string>();
  private skipped = 0;
  private truncated = false;

  constructor(
    readonly name: string,
    files: Iterable<File>,
  ) {
    for (const file of files) {
      // webkitRelativePath is "<selected-folder>/<path within it>".
      const relative = file.webkitRelativePath.split("/").slice(1).join("/");
      if (!relative || isIgnoredPath(relative)) {
        this.skipped += 1;
        continue;
      }
      if (this.originals.size >= MAX_PROJECT_ENTRIES) {
        this.truncated = true;
        this.skipped += 1;
        continue;
      }
      this.originals.set(relative, file);
    }
  }

  /** Name of the selected folder, derived from the first file's relative path. */
  static folderName(files: ArrayLike<File>): string {
    return files.length > 0 ? files[0].webkitRelativePath.split("/")[0] || "project" : "project";
  }

  async list(): Promise<SourceListing> {
    const paths = new Set([...this.originals.keys(), ...this.saved.keys()]);
    const folders = new Set<ProjectPath>();
    for (const path of paths) ancestorPaths(path).forEach((folder) => folders.add(folder));
    const entries: ProjectEntry[] = [
      ...[...folders].map((path) => ({ path, type: "folder" as const })),
      ...[...paths].map((path) => ({
        path,
        type: "file" as const,
        size: this.originals.get(path)?.size,
      })),
    ];
    return { entries, skipped: this.skipped, truncated: this.truncated };
  }

  async read(path: ProjectPath): Promise<string> {
    const saved = this.saved.get(path);
    if (saved !== undefined) return saved;
    const file = this.originals.get(path);
    if (!file) throw new SourceError("not-found", `${path} does not exist.`);
    return decodeTextFile(file, path);
  }

  async write(path: ProjectPath, content: string): Promise<void> {
    this.saved.set(path, content);
  }

  async createFile(path: ProjectPath): Promise<void> {
    if (this.originals.has(path) || this.saved.has(path)) {
      throw new SourceError("exists", `${path} already exists.`);
    }
    this.saved.set(path, "");
  }
}
