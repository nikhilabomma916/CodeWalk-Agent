import { isIgnoredPath } from "@/lib/project-paths";
import { importFiles } from "@/services/api/projects";

import { decodeTextFile } from "./sources/decode";
import { MAX_EDITABLE_FILE_BYTES, MAX_PROJECT_ENTRIES, SourceError } from "./sources/types";

/** Files per upload request (the server accepts at most 100). */
export const UPLOAD_BATCH_FILES = 100;
/** Bytes per upload request, kept well below the server's request body limit (6 MB by default). */
export const UPLOAD_BATCH_BYTES = 4 * 1024 * 1024;

export interface SkippedFile {
  path: string;
  reason: string;
}

/** A folder picked with <input webkitdirectory>, filtered before anything is read or sent. */
export interface FolderSelection {
  name: string;
  files: { path: string; file: File }[];
  skipped: SkippedFile[];
  /** More than MAX_PROJECT_ENTRIES files: the rest were not selected. */
  truncated: boolean;
  totalBytes: number;
}

export function selectFolder(list: ArrayLike<File>): FolderSelection {
  const all = Array.from(list);
  const name = all[0]?.webkitRelativePath.split("/")[0] || "project";
  const selection: FolderSelection = {
    name,
    files: [],
    skipped: [],
    truncated: false,
    totalBytes: 0,
  };
  for (const file of all) {
    // webkitRelativePath is "<selected-folder>/<path within it>".
    const path = file.webkitRelativePath.split("/").slice(1).join("/");
    if (!path) continue;
    if (isIgnoredPath(path)) {
      selection.skipped.push({ path, reason: "dependency, build, or secret file" });
    } else if (file.size > MAX_EDITABLE_FILE_BYTES) {
      selection.skipped.push({ path, reason: "larger than 2 MB" });
    } else if (selection.files.length >= MAX_PROJECT_ENTRIES) {
      selection.truncated = true;
    } else {
      selection.files.push({ path, file });
      selection.totalBytes += file.size;
    }
  }
  selection.files.sort((a, b) => a.path.localeCompare(b.path));
  return selection;
}

export interface UploadProgress {
  /** Files read and sent (or skipped) so far. */
  done: number;
  total: number;
  uploaded: number;
}

export interface UploadOutcome {
  uploaded: number;
  skipped: SkippedFile[];
}

const encoder = new TextEncoder();

/**
 * Reads the selected files as text and uploads them in batches. Binary files are skipped here;
 * the server checks every file again (paths, credentials, size, existing files) and reports what
 * it skipped. Stops between batches when `signal` is aborted (throws the abort reason); files
 * already uploaded stay in the project.
 */
export async function uploadFolder(
  projectId: string,
  selection: FolderSelection,
  options: { signal?: AbortSignal; onProgress?(progress: UploadProgress): void } = {},
): Promise<UploadOutcome> {
  const { signal, onProgress } = options;
  const total = selection.files.length;
  const skipped: SkippedFile[] = [];
  let uploaded = 0;
  let done = 0;
  let batch: { path: string; content: string }[] = [];
  let batchBytes = 0;

  const send = async () => {
    if (batch.length === 0) return;
    const result = await importFiles(projectId, batch, { signal });
    uploaded += result.created.length;
    skipped.push(...result.skipped.map((s) => ({ path: s.path, reason: s.message })));
    done += batch.length;
    batch = [];
    batchBytes = 0;
    onProgress?.({ done, total, uploaded });
  };

  for (const { path, file } of selection.files) {
    signal?.throwIfAborted();
    let content: string;
    try {
      content = await decodeTextFile(file, path);
    } catch (error) {
      if (!(error instanceof SourceError)) throw error;
      skipped.push({ path, reason: error.reason === "binary" ? "binary file" : error.message });
      done += 1;
      continue;
    }
    const bytes = encoder.encode(content).length + path.length + 32;
    if (
      batch.length >= UPLOAD_BATCH_FILES ||
      (batch.length > 0 && batchBytes + bytes > UPLOAD_BATCH_BYTES)
    ) {
      await send();
      signal?.throwIfAborted();
    }
    batch.push({ path, content });
    batchBytes += bytes;
  }
  await send();
  onProgress?.({ done: total, total, uploaded });
  return { uploaded, skipped };
}
