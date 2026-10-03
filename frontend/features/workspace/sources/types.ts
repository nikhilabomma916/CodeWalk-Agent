import type { ProjectEntry, ProjectPath } from "@/types/project";

/**
 * Where a project's files come from and where saves go.
 *
 * The workspace talks only to this interface: browser-local folders, in-memory
 * projects, and server (database) projects are interchangeable for the UI.
 */
export interface ProjectSource {
  readonly kind: "memory" | "local-directory" | "local-snapshot" | "server";
  readonly name: string;
  /**
   * Where saved changes end up. Shown to the user so it is always clear
   * whether "Save" writes to disk, to the server, or only to this browser tab.
   */
  readonly persistence: "disk" | "browser-memory" | "server";
  /** True when files cannot be edited (server projects linked to a folder). */
  readonly readOnly: boolean;
  /** Set for projects stored by the backend. */
  readonly serverProjectId?: string;
  list(): Promise<SourceListing>;
  read(path: ProjectPath): Promise<string>;
  write(path: ProjectPath, content: string): Promise<void>;
  createFile(path: ProjectPath): Promise<void>;
}

export interface SourceListing {
  entries: ProjectEntry[];
  /** Entries skipped by ignore rules or limits (dependency folders, secrets, ...). */
  skipped: number;
  /** True when the entry limit was reached and the listing is incomplete. */
  truncated: boolean;
}

export type SourceErrorReason =
  "binary" | "too-large" | "not-found" | "exists" | "permission" | "io" | "read-only";

export class SourceError extends Error {
  readonly reason: SourceErrorReason;

  constructor(reason: SourceErrorReason, message: string, options?: { cause?: unknown }) {
    super(message, options);
    this.name = "SourceError";
    this.reason = reason;
  }
}

/** Files larger than this are listed but not opened in the editor. */
export const MAX_EDITABLE_FILE_BYTES = 2 * 1024 * 1024;
/** Upper bound on listed entries so opening a huge folder cannot freeze the tab. */
export const MAX_PROJECT_ENTRIES = 10_000;
