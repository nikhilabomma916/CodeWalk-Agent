"use client";

import { useEffect, useId, useRef, useState, type FormEvent } from "react";

import { SourceError } from "@/features/workspace/sources/types";

export interface PathDialogRequest {
  title: string;
  label: string;
  /** Initial value; the part after the last "/" (before the extension, for files) is selected. */
  initial: string;
  submitLabel: string;
  hint?: string;
  /** Performs the operation; rejects with a SourceError (or Error) whose message is shown. */
  onSubmit(value: string): Promise<void>;
}

/** Returns an error message for an unusable project path, or null. */
export function validateProjectPath(value: string): string | null {
  const path = value.trim();
  if (!path) return "Enter a path.";
  if (path.startsWith("/") || /^[a-zA-Z]:/.test(path)) return "Use a path inside the project.";
  if (path.includes("\\")) return "Use / to separate folders.";
  if (path.split("/").some((part) => part === "" || part === "." || part === ".."))
    return "The path has an empty, '.' or '..' part.";
  if (/[<>:"|?*\u0000-\u001f]/.test(path))
    return 'The path contains a character that is not allowed (<>:"|?*).';
  if (path.length > 1024) return "The path is too long.";
  return null;
}

/** New File / New Folder / Rename / Move: one path, validated here and by the project source. */
export function PathDialog({
  request,
  onClose,
}: {
  request: PathDialogRequest | null;
  onClose(): void;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const inputId = useId();
  const errorId = useId();
  const hintId = useId();

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (request && !dialog.open) {
      setValue(request.initial);
      setError(null);
      setBusy(false);
      dialog.showModal();
      // Select the name (VS Code style), not the folder or extension.
      requestAnimationFrame(() => {
        const input = inputRef.current;
        if (!input) return;
        const start = request.initial.lastIndexOf("/") + 1;
        const dot = request.initial.lastIndexOf(".");
        input.focus();
        input.setSelectionRange(start, dot > start ? dot : request.initial.length);
      });
    } else if (!request && dialog.open) dialog.close();
  }, [request]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!request) return;
    const path = value.trim().replace(/\/+$/, "");
    const invalid = validateProjectPath(path);
    if (invalid) {
      setError(invalid);
      return;
    }
    setBusy(true);
    try {
      await request.onSubmit(path);
      onClose();
    } catch (cause) {
      setError(
        cause instanceof SourceError || cause instanceof Error
          ? cause.message
          : "The operation failed.",
      );
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
      className="m-auto w-[min(28rem,calc(100vw-2rem))] rounded-md border border-border bg-surface p-0 text-fg shadow-xl backdrop:bg-black/60"
    >
      <form onSubmit={submit}>
        <div className="space-y-3 p-4">
          <h2 id={`${inputId}-title`} className="text-sm font-semibold">
            {request?.title}
          </h2>
          <div>
            <label htmlFor={inputId} className="block text-xs text-fg-muted">
              {request?.label}
            </label>
            <input
              id={inputId}
              ref={inputRef}
              value={value}
              disabled={busy}
              maxLength={1024}
              autoComplete="off"
              spellCheck={false}
              aria-invalid={!!error}
              aria-describedby={[error ? errorId : null, request?.hint ? hintId : null]
                .filter(Boolean)
                .join(" ")}
              onChange={(event) => {
                setValue(event.target.value);
                setError(null);
              }}
              className="mt-1 w-full rounded border border-border bg-surface-sunken px-2 py-1.5 font-mono text-sm outline-none focus:border-accent"
            />
            {request?.hint && (
              <p id={hintId} className="mt-1 text-[11px] text-fg-subtle">
                {request.hint}
              </p>
            )}
          </div>
          {error && (
            <p id={errorId} role="alert" className="text-xs text-danger">
              {error}
            </p>
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
            {busy ? "Working…" : request?.submitLabel}
          </button>
        </div>
      </form>
    </dialog>
  );
}
