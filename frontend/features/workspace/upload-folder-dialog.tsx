"use client";

import { Loader2 } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { isApiError } from "@/services/api/errors";
import { createProject, type ServerProject } from "@/services/api/projects";

import {
  uploadFolder,
  type FolderSelection,
  type SkippedFile,
  type UploadProgress,
} from "./folder-upload";
import type { ServerAvailability } from "./use-server-projects";

const MAX_NAME_LENGTH = 100;

type Stage =
  | { step: "review" }
  | { step: "uploading"; progress: UploadProgress }
  | {
      step: "done";
      project: ServerProject;
      uploaded: number;
      skipped: SkippedFile[];
      cancelled: boolean;
    }
  | { step: "error"; message: string; project: ServerProject | null };

interface UploadFolderDialogProps {
  /** The picked folder; null while the dialog is closed. */
  selection: FolderSelection | null;
  server: ServerAvailability;
  onClose(): void;
  /** Opens the uploaded project's analysis view in the Uploads area. */
  onOpenProject(project: ServerProject): Promise<void>;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function SkippedList({ items }: { items: SkippedFile[] }) {
  if (items.length === 0) return null;
  return (
    <details className="text-xs">
      <summary className="cursor-pointer text-fg-muted">
        {items.length} file{items.length === 1 ? "" : "s"} skipped
      </summary>
      <ul
        aria-label="Skipped files"
        className="mt-1 max-h-40 space-y-0.5 overflow-auto font-mono text-[11px]"
      >
        {items.slice(0, 500).map((item) => (
          <li key={`${item.path}:${item.reason}`}>
            {item.path} <span className="font-sans text-fg-subtle">— {item.reason}</span>
          </li>
        ))}
      </ul>
    </details>
  );
}

/** Uploads a folder from this computer into a new server project (Module 18). */
export function UploadFolderDialog({
  selection,
  server,
  onClose,
  onOpenProject,
}: UploadFolderDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const abort = useRef<AbortController | null>(null);
  const uploadedSoFar = useRef(0);
  const [name, setName] = useState("");
  const [nameError, setNameError] = useState<string | null>(null);
  const [stage, setStage] = useState<Stage>({ step: "review" });
  const [opening, setOpening] = useState(false);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (selection && !dialog.open) {
      setName(selection.name.slice(0, MAX_NAME_LENGTH));
      setNameError(null);
      setStage({ step: "review" });
      dialog.showModal();
    } else if (!selection && dialog.open) dialog.close();
  }, [selection]);

  if (!selection) return <dialog ref={dialogRef} aria-label="Upload folder" />;

  const uploading = stage.step === "uploading";
  const close = () => {
    if (uploading) return;
    onClose();
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) return setNameError("Enter a project name.");
    if (trimmed.length > MAX_NAME_LENGTH)
      return setNameError(`Use at most ${MAX_NAME_LENGTH} characters.`);
    if (/[\\/]/.test(trimmed)) return setNameError("Project names cannot contain slashes.");
    const controller = new AbortController();
    abort.current = controller;
    const total = selection.files.length;
    uploadedSoFar.current = 0;
    setStage({ step: "uploading", progress: { done: 0, total, uploaded: 0 } });
    let project: ServerProject | null = null;
    try {
      project = await createProject({
        name: trimmed,
        description: `Uploaded from the local folder “${selection.name}”.`,
        origin: "upload",
      });
      const created = project;
      const outcome = await uploadFolder(created.id, selection, {
        signal: controller.signal,
        onProgress: (progress) => {
          uploadedSoFar.current = progress.uploaded;
          setStage({ step: "uploading", progress });
        },
      });
      setStage({ step: "done", project: created, ...outcome, cancelled: false });
    } catch (error) {
      if (controller.signal.aborted && project) {
        setStage({
          step: "done",
          project,
          uploaded: uploadedSoFar.current,
          skipped: [],
          cancelled: true,
        });
      } else {
        setStage({
          step: "error",
          project,
          message: isApiError(error) ? error.message : "The folder could not be uploaded.",
        });
      }
    } finally {
      abort.current = null;
    }
  };

  const open = async (project: ServerProject) => {
    setOpening(true);
    try {
      await onOpenProject(project);
    } finally {
      setOpening(false);
    }
  };

  const primary =
    "rounded bg-accent px-3 py-1.5 text-xs font-medium text-white hover:bg-accent-strong disabled:opacity-60";
  const secondary =
    "rounded border border-border px-3 py-1.5 text-xs hover:bg-surface-hover disabled:opacity-60";
  const preSkipped = selection.skipped;

  return (
    <dialog
      ref={dialogRef}
      aria-labelledby="upload-folder-title"
      onCancel={(event) => {
        event.preventDefault();
        close();
      }}
      className="m-auto w-[min(30rem,calc(100vw-2rem))] rounded-md border border-border bg-surface p-0 text-fg shadow-xl backdrop:bg-black/60"
    >
      <form onSubmit={submit}>
        <div className="space-y-3 p-4">
          <h2 id="upload-folder-title" className="text-sm font-semibold">
            Upload folder to a new project
          </h2>

          {stage.step === "review" && (
            <>
              <p className="text-xs text-fg-muted">
                <span className="font-mono text-fg">{selection.name}</span>:{" "}
                {selection.files.length} file
                {selection.files.length === 1 ? "" : "s"} ({formatBytes(selection.totalBytes)}) will
                be uploaded to the CodeWalk server and stored in a new project under Uploads.
                Dependency and build folders (node_modules, .git, …), .env and other credential
                files, binary files, and files over 2 MB are not uploaded. Code is analyzed, never
                executed.
              </p>
              {selection.truncated && (
                <p className="text-xs text-warning">
                  The folder has more files than a project can hold; only the first{" "}
                  {selection.files.length} are uploaded.
                </p>
              )}
              <SkippedList items={preSkipped} />
              <div>
                <label htmlFor="upload-project-name" className="block text-xs text-fg-muted">
                  Project name
                </label>
                <input
                  id="upload-project-name"
                  autoFocus
                  value={name}
                  maxLength={MAX_NAME_LENGTH + 20}
                  aria-invalid={!!nameError}
                  aria-describedby={nameError ? "upload-project-name-error" : undefined}
                  onChange={(event) => {
                    setName(event.target.value);
                    setNameError(null);
                  }}
                  className="mt-1 w-full rounded border border-border bg-surface-sunken px-2 py-1.5 text-sm outline-none focus:border-accent"
                />
              </div>
              {nameError && (
                <p id="upload-project-name-error" role="alert" className="text-xs text-danger">
                  {nameError}
                </p>
              )}
              {!server.available && (
                <p role="alert" className="text-xs text-danger">
                  {server.reason}
                </p>
              )}
              {selection.files.length === 0 && (
                <p role="alert" className="text-xs text-danger">
                  Nothing to upload: every file in this folder is skipped.
                </p>
              )}
            </>
          )}

          {stage.step === "uploading" && (
            <div className="space-y-2">
              <p role="status" className="flex items-center gap-1.5 text-xs text-fg-muted">
                <Loader2 aria-hidden className="size-3.5 animate-spin" />
                Uploading {stage.progress.done} of {stage.progress.total} files…
              </p>
              <progress
                aria-label="Upload progress"
                max={Math.max(stage.progress.total, 1)}
                value={stage.progress.done}
                className="h-2 w-full accent-accent"
              />
            </div>
          )}

          {stage.step === "done" && (
            <div className="space-y-2">
              <p role="status" className="text-xs text-fg">
                {stage.cancelled
                  ? `Upload cancelled. “${stage.project.name}” keeps the ${stage.uploaded} file${stage.uploaded === 1 ? "" : "s"} uploaded before you cancelled.`
                  : `Uploaded ${stage.uploaded} file${stage.uploaded === 1 ? "" : "s"} to “${stage.project.name}”.`}
              </p>
              <SkippedList items={[...preSkipped, ...stage.skipped]} />
              <p className="text-[11px] text-fg-subtle">
                Opening the project analyzes it (files, symbols, imports) so you can search it, see
                its architecture and impact, and ask the agent about it. Uploaded projects appear
                under Uploads only; the agent answers questions but never changes their files.
              </p>
            </div>
          )}

          {stage.step === "error" && (
            <div className="space-y-1">
              <p role="alert" className="text-xs text-danger">
                {stage.message}
              </p>
              {stage.project && (
                <p className="text-[11px] text-fg-muted">
                  The project “{stage.project.name}” was created and keeps any files uploaded before
                  the error.
                </p>
              )}
            </div>
          )}
        </div>

        <div className="flex justify-end gap-2 border-t border-border bg-surface-sunken px-4 py-3">
          {stage.step === "review" && (
            <>
              <button type="button" onClick={close} className={secondary}>
                Cancel
              </button>
              <button
                type="submit"
                disabled={!server.available || selection.files.length === 0}
                className={primary}
              >
                Upload {selection.files.length} file{selection.files.length === 1 ? "" : "s"}
              </button>
            </>
          )}
          {stage.step === "uploading" && (
            <button type="button" onClick={() => abort.current?.abort()} className={secondary}>
              Cancel upload
            </button>
          )}
          {(stage.step === "done" || stage.step === "error") && (
            <>
              <button type="button" onClick={close} disabled={opening} className={secondary}>
                Close
              </button>
              {stage.project && (
                <button
                  type="button"
                  disabled={opening}
                  onClick={() => stage.project && void open(stage.project)}
                  className={primary}
                >
                  {opening ? "Opening…" : "Open project"}
                </button>
              )}
            </>
          )}
        </div>
      </form>
    </dialog>
  );
}
