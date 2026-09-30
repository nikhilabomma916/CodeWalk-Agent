"use client";

import { useState, type FormEvent } from "react";

import { SourceError } from "@/features/workspace/sources/types";
import { validateNewFilePath } from "@/lib/project-paths";

interface NewFileFormProps {
  /** Folder the new file is created in; "" for the project root. */
  parentPath: string;
  onCreate(path: string): Promise<void>;
  onDone(): void;
}

export function NewFileForm({ parentPath, onCreate, onDone }: NewFileFormProps) {
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const validation = validateNewFilePath(value);
    if (validation) {
      setError(validation);
      return;
    }
    const path = parentPath ? `${parentPath}/${value.trim()}` : value.trim();
    setBusy(true);
    try {
      await onCreate(path);
      onDone();
    } catch (cause) {
      setError(cause instanceof SourceError ? cause.message : "The file could not be created.");
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="border-b border-border px-2 py-1.5">
      <label htmlFor="new-file-input" className="mb-1 block text-[11px] text-fg-muted">
        New file in {parentPath ? <span className="font-mono">{parentPath}/</span> : "project root"}
      </label>
      <input
        id="new-file-input"
        autoFocus
        value={value}
        disabled={busy}
        placeholder="e.g. src/main.py"
        aria-invalid={!!error}
        aria-describedby={error ? "new-file-error" : undefined}
        onChange={(event) => {
          setValue(event.target.value);
          setError(null);
        }}
        onKeyDown={(event) => event.key === "Escape" && onDone()}
        onBlur={() => !value.trim() && onDone()}
        className="w-full rounded border border-border bg-surface-sunken px-1.5 py-1 font-mono text-xs text-fg outline-none focus:border-accent"
      />
      {error && (
        <p id="new-file-error" role="alert" className="mt-1 text-[11px] text-danger">
          {error}
        </p>
      )}
    </form>
  );
}
