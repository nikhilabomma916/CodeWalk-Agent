"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";

import type { ServerAvailability } from "./use-server-projects";

const MAX_NAME_LENGTH = 100;

export type ProjectStorage = "server" | "browser";

export interface NewProjectRequest {
  name: string;
  storage: ProjectStorage;
  /** Server workspace folder to link (server storage only). */
  rootPath?: string;
}

interface NewProjectDialogProps {
  open: boolean;
  server: ServerAvailability;
  /** Folders under the server workspace root that can be linked; null when linking is disabled. */
  workspaceFolders: string[] | null;
  /** Resolves to an error message to show, or null on success. */
  onCreate(request: NewProjectRequest): Promise<string | null>;
  onClose(): void;
}

export function NewProjectDialog({
  open,
  server,
  workspaceFolders,
  onCreate,
  onClose,
}: NewProjectDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [name, setName] = useState("");
  const [storage, setStorage] = useState<ProjectStorage>("server");
  const [rootPath, setRootPath] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const effectiveStorage: ProjectStorage = server.available ? storage : "browser";

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    else if (!open && dialog.open) dialog.close();
  }, [open]);

  const reset = () => {
    setName("");
    setRootPath("");
    setError(null);
    setBusy(false);
  };

  const close = () => {
    reset();
    onClose();
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) return setError("Enter a project name.");
    if (trimmed.length > MAX_NAME_LENGTH)
      return setError(`Use at most ${MAX_NAME_LENGTH} characters.`);
    if (/[\\/]/.test(trimmed)) return setError("Project names cannot contain slashes.");
    setBusy(true);
    const failure = await onCreate({
      name: trimmed,
      storage: effectiveStorage,
      rootPath: effectiveStorage === "server" && rootPath ? rootPath : undefined,
    });
    if (failure) {
      setError(failure);
      setBusy(false);
    } else {
      reset();
    }
  };

  const radio =
    "flex items-start gap-2 rounded border border-border p-2 text-xs has-[:checked]:border-accent";

  return (
    <dialog
      ref={dialogRef}
      aria-labelledby="new-project-title"
      onCancel={(event) => {
        event.preventDefault();
        close();
      }}
      className="m-auto w-[min(28rem,calc(100vw-2rem))] rounded-md border border-border bg-surface p-0 text-fg shadow-xl backdrop:bg-black/60"
    >
      <form onSubmit={submit}>
        <div className="space-y-3 p-4">
          <h2 id="new-project-title" className="text-sm font-semibold">
            New project
          </h2>
          <div>
            <label htmlFor="project-name" className="block text-xs text-fg-muted">
              Project name
            </label>
            <input
              id="project-name"
              autoFocus
              value={name}
              disabled={busy}
              maxLength={MAX_NAME_LENGTH + 20}
              aria-invalid={!!error}
              aria-describedby={error ? "project-name-error" : undefined}
              onChange={(event) => {
                setName(event.target.value);
                setError(null);
              }}
              className="mt-1 w-full rounded border border-border bg-surface-sunken px-2 py-1.5 text-sm outline-none focus:border-accent"
            />
          </div>

          <fieldset className="space-y-1.5">
            <legend className="mb-1 text-xs text-fg-muted">Storage</legend>
            <label className={`${radio} ${server.available ? "" : "opacity-50"}`}>
              <input
                type="radio"
                name="storage"
                value="server"
                checked={effectiveStorage === "server"}
                disabled={!server.available || busy}
                onChange={() => setStorage("server")}
                className="mt-0.5 accent-accent"
              />
              <span>
                <span className="block text-fg">Server</span>
                <span className="text-fg-muted">
                  {server.available
                    ? "Saved in the CodeWalk database; survives reloads and enables project analysis."
                    : server.reason}
                </span>
              </span>
            </label>
            <label className={radio}>
              <input
                type="radio"
                name="storage"
                value="browser"
                checked={effectiveStorage === "browser"}
                disabled={busy}
                onChange={() => setStorage("browser")}
                className="mt-0.5 accent-accent"
              />
              <span>
                <span className="block text-fg">This browser tab</span>
                <span className="text-fg-muted">
                  Not persisted; files are lost when the tab closes.
                </span>
              </span>
            </label>
          </fieldset>

          {effectiveStorage === "server" && workspaceFolders !== null && (
            <div>
              <label htmlFor="project-root" className="block text-xs text-fg-muted">
                Link a server folder (optional)
              </label>
              <select
                id="project-root"
                value={rootPath}
                disabled={busy}
                onChange={(event) => setRootPath(event.target.value)}
                className="mt-1 w-full rounded border border-border bg-surface-sunken px-2 py-1.5 text-sm"
              >
                <option value="">None — start with an empty project</option>
                {workspaceFolders.map((folder) => (
                  <option key={folder} value={folder}>
                    {folder}
                  </option>
                ))}
              </select>
              {rootPath && (
                <p className="mt-1 text-[11px] text-fg-muted">
                  Files are imported by scanning the folder and are read-only in the editor.
                </p>
              )}
            </div>
          )}

          {error && (
            <p id="project-name-error" role="alert" className="text-xs text-danger">
              {error}
            </p>
          )}
        </div>
        <div className="flex justify-end gap-2 border-t border-border bg-surface-sunken px-4 py-3">
          <button
            type="button"
            onClick={close}
            className="rounded border border-border px-3 py-1.5 text-xs hover:bg-surface-hover"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={busy}
            className="rounded bg-accent px-3 py-1.5 text-xs font-medium text-white hover:bg-accent-strong disabled:opacity-60"
          >
            {busy ? "Creating…" : "Create"}
          </button>
        </div>
      </form>
    </dialog>
  );
}
