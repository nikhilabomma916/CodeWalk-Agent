"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";

const MAX_NAME_LENGTH = 80;

interface NewProjectDialogProps {
  open: boolean;
  onCreate(name: string): void;
  onClose(): void;
}

export function NewProjectDialog({ open, onCreate, onClose }: NewProjectDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      setName("");
      setError(null);
      dialog.showModal();
    } else if (!open && dialog.open) {
      dialog.close();
    }
  }, [open]);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) return setError("Enter a project name.");
    if (trimmed.length > MAX_NAME_LENGTH)
      return setError(`Use at most ${MAX_NAME_LENGTH} characters.`);
    if (/[\\/]/.test(trimmed)) return setError("Project names cannot contain slashes.");
    onCreate(trimmed);
  };

  return (
    <dialog
      ref={dialogRef}
      aria-labelledby="new-project-title"
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      className="m-auto w-[min(26rem,calc(100vw-2rem))] rounded-md border border-border bg-surface p-0 text-fg shadow-xl backdrop:bg-black/60"
    >
      <form onSubmit={submit}>
        <div className="p-4">
          <h2 id="new-project-title" className="text-sm font-semibold">
            New project
          </h2>
          <p className="mt-1 text-xs text-fg-muted">
            The project is kept in this browser tab. Its files are lost when the tab is closed or
            reloaded.
          </p>
          <label htmlFor="project-name" className="mt-3 block text-xs text-fg-muted">
            Project name
          </label>
          <input
            id="project-name"
            autoFocus
            value={name}
            maxLength={MAX_NAME_LENGTH + 20}
            aria-invalid={!!error}
            aria-describedby={error ? "project-name-error" : undefined}
            onChange={(event) => {
              setName(event.target.value);
              setError(null);
            }}
            className="mt-1 w-full rounded border border-border bg-surface-sunken px-2 py-1.5 text-sm outline-none focus:border-accent"
          />
          {error && (
            <p id="project-name-error" role="alert" className="mt-1 text-xs text-danger">
              {error}
            </p>
          )}
        </div>
        <div className="flex justify-end gap-2 border-t border-border bg-surface-sunken px-4 py-3">
          <button
            type="button"
            onClick={onClose}
            className="rounded border border-border px-3 py-1.5 text-xs hover:bg-surface-hover"
          >
            Cancel
          </button>
          <button
            type="submit"
            className="rounded bg-accent px-3 py-1.5 text-xs font-medium text-white hover:bg-accent-strong"
          >
            Create
          </button>
        </div>
      </form>
    </dialog>
  );
}
