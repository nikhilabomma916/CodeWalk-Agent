import { isIgnoredName, joinPath } from "@/lib/project-paths";
import type { ProjectEntry, ProjectPath } from "@/types/project";

import { decodeTextFile } from "./decode";
import { MAX_PROJECT_ENTRIES, SourceError, type ProjectSource, type SourceListing } from "./types";

export function supportsDirectoryAccess(): boolean {
  return typeof window !== "undefined" && typeof window.showDirectoryPicker === "function";
}

function toSourceError(error: unknown, path: string): SourceError {
  if (error instanceof SourceError) return error;
  const name = error instanceof DOMException ? error.name : "";
  if (name === "NotFoundError")
    return new SourceError("not-found", `${path} no longer exists on disk.`, { cause: error });
  if (name === "NotAllowedError" || name === "SecurityError") {
    return new SourceError("permission", `Permission to access ${path} was denied.`, {
      cause: error,
    });
  }
  return new SourceError("io", `Could not access ${path}.`, { cause: error });
}

/**
 * A real folder on the user's disk opened through the File System Access API.
 * Saving writes the file back to disk.
 */
export class LocalDirectorySource implements ProjectSource {
  readonly kind = "local-directory";
  readonly persistence = "disk";
  readonly readOnly = false;
  readonly name: string;

  constructor(private readonly root: FileSystemDirectoryHandle) {
    this.name = root.name;
  }

  async list(): Promise<SourceListing> {
    const entries: ProjectEntry[] = [];
    let skipped = 0;
    let truncated = false;

    const walk = async (
      directory: FileSystemDirectoryHandle,
      prefix: ProjectPath,
    ): Promise<void> => {
      for await (const [name, handle] of directory.entries()) {
        const type = handle.kind === "directory" ? "folder" : "file";
        if (isIgnoredName(name, type)) {
          skipped += 1;
          continue;
        }
        if (entries.length >= MAX_PROJECT_ENTRIES) {
          truncated = true;
          return;
        }
        const path = joinPath(prefix, name);
        entries.push({ path, type });
        if (handle.kind === "directory") await walk(handle as FileSystemDirectoryHandle, path);
      }
    };

    try {
      await walk(this.root, "");
    } catch (error) {
      throw toSourceError(error, this.name);
    }
    return { entries, skipped, truncated };
  }

  private async fileHandle(path: ProjectPath, create = false): Promise<FileSystemFileHandle> {
    const segments = path.split("/");
    const fileName = segments.pop();
    if (!fileName) throw new SourceError("not-found", "Empty path.");
    let directory = this.root;
    for (const segment of segments) {
      directory = await directory.getDirectoryHandle(segment, { create });
    }
    return directory.getFileHandle(fileName, { create });
  }

  async read(path: ProjectPath): Promise<string> {
    try {
      const file = await (await this.fileHandle(path)).getFile();
      return await decodeTextFile(file, path);
    } catch (error) {
      throw toSourceError(error, path);
    }
  }

  async write(path: ProjectPath, content: string): Promise<void> {
    try {
      const writable = await (await this.fileHandle(path)).createWritable();
      await writable.write(content);
      await writable.close();
    } catch (error) {
      throw toSourceError(error, path);
    }
  }

  async createFile(path: ProjectPath): Promise<void> {
    try {
      await this.fileHandle(path);
      throw new SourceError("exists", `${path} already exists.`);
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "NotFoundError"))
        throw toSourceError(error, path);
    }
    try {
      const writable = await (await this.fileHandle(path, true)).createWritable();
      await writable.close();
    } catch (error) {
      throw toSourceError(error, path);
    }
  }
}
