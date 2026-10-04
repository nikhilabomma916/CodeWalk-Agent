"use client";

import { useEffect, useId, useRef, useState, type FormEvent } from "react";

import { SourceError } from "@/features/workspace/sources/types";
import { CODE_FILE_EXTENSIONS, validateCodeFileName } from "@/lib/code-files";

interface CodeFileDialogProps {
  open: boolean;
  onClose(): void;
  /** Creates and opens the file; rejects with a SourceError to show. */
  onCreate(name: string): Promise<void>;
  /** Opens a file that already exists (offered when the name is taken). */
  onOpenExisting(name: string): void;
}

/** Coding "+ New File": a file name only; the file is created at the project root and opened. */
export function CodeFileDialog({ open, onClose, onCreate, onOpenExisting }: CodeFileDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [existing, setExisting] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const inputId = useId();
  const errorId = useId();
  const hintId = useId();

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      setName("");
      setError(null);
      setExisting(null);
      setBusy(false);
      dialog.showModal();
    } else if (!open && dialog.open) dialog.close();
  }, [open]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const fileName = name.trim();
    const invalid = validateCodeFileName(fileName);
    if (invalid) {
      setError(invalid);
      return;
    }
    setBusy(true);
    try {
      await onCreate(fileName);
      onClose();
    } catch (cause) {
      if (cause instanceof SourceError && cause.reason === "exists") {
        setError(`${fileName} already exists.`);
        setExisting(fileName);
      } else {
        setError(cause instanceof SourceError ? cause.message : "The file could not be created.");
      }
      setBusy(false);
    }
  };

  return (
    <dialog
      ref={dialogRef}
      aria-labelledby={`${inputId}-title`}
      onCancel={(event) => {
        event.preventDefault();
        if (!busy) onClose();
      }}
      className="m-auto w-[min(26rem,calc(100vw-2rem))] rounded-md border border-border bg-surface p-0 text-fg shadow-xl backdrop:bg-black/60"
    >
      <form onSubmit={submit}>
        <div className="space-y-3 p-4">
          <h2 id={`${inputId}-title`} className="text-sm font-semibold">
            Create code file
          </h2>
          <div>
            <label htmlFor={inputId} className="block text-xs text-fg-muted">
              File name
            </label>
            <input
              id={inputId}
              autoFocus
              value={name}
              disabled={busy}
              placeholder="main.py"
              maxLength={300}
              autoComplete="off"
              spellCheck={false}
              aria-invalid={!!error}
              aria-describedby={error ? `${errorId} ${hintId}` : hintId}
              onChange={(event) => {
                setName(event.target.value);
                setError(null);
                setExisting(null);
              }}
              className="mt-1 w-full rounded border border-border bg-surface-sunken px-2 py-1.5 font-mono text-sm outline-none focus:border-accent"
            />
            <p id={hintId} className="mt-1 text-[11px] text-fg-subtle">
              Created at the project root. Supported: {CODE_FILE_EXTENSIONS.join(" ")}
            </p>
          </div>
          {error && (
            <div id={errorId} role="alert" className="space-y-1.5 text-xs text-danger">
              <p>{error}</p>
              {existing && (
                <button
                  type="button"
                  onClick={() => {
                    onOpenExisting(existing);
                    onClose();
                  }}
                  className="rounded border border-border px-2 py-1 text-fg hover:bg-surface-hover"
                >
                  Open existing file
                </button>
              )}
            </div>
          )}
        </div>
        <div className="flex justify-end gap-2 border-t border-border bg-surface-sunken px-4 py-3">
          <button
            type="button"
            disabled={busy}
            onClick={onClose}
            className="rounded border border-border px-3 py-1.5 text-xs hover:bg-surface-hover disabled:opacity-60"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={busy}
            className="rounded bg-accent px-3 py-1.5 text-xs font-medium text-on-accent hover:bg-accent-strong hover:text-on-accent-hover disabled:opacity-60"
          >
            {busy ? "Creating…" : "Create"}
          </button>
        </div>
      </form>
    </dialog>
  );
}
