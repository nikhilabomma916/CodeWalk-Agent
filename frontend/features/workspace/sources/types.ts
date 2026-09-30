import type { ProjectEntry, ProjectPath } from "@/types/project";

/**
 * Where a project's files come from and where saves go.
 *
 * The workspace talks only to this interface, so a backend-backed source
 * (project/file APIs) can be added without changing UI components.
 */
export interface ProjectSource {
  readonly kind: "memory" | "local-directory" | "local-snapshot";
  readonly name: string;
  /**
   * Where saved changes end up. Shown to the user so it is always clear
   * whether "Save" writes to disk or only to this browser tab.
   */
  readonly persistence: "disk" | "browser-memory";
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
  "binary" | "too-large" | "not-found" | "exists" | "permission" | "io";

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
