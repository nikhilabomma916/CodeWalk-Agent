"use client";

import { FolderOpen, FolderPlus } from "lucide-react";

import { StateMessage } from "@/components/ui/state-message";

import { useWorkspace } from "./workspace-context";

interface WelcomeProps {
  onNewProject(): void;
  onOpenFolder(): void;
}

export function Welcome({ onNewProject, onOpenFolder }: WelcomeProps) {
  const { state, canOpenDirectory } = useWorkspace();

  if (state.projectStatus === "loading") return <StateMessage title="Loading project…" />;

  const button =
    "flex items-center gap-2 rounded border border-border bg-surface-raised px-3 py-2 text-sm text-fg hover:border-border-strong hover:bg-surface-hover";

  return (
    <div className="flex h-full items-center justify-center overflow-auto bg-surface p-6">
      <div className="w-full max-w-md">
        <h1 className="text-lg font-semibold text-fg">CodeWalk Agent</h1>
        <p className="mt-1 text-sm text-fg-muted">Open a project to start editing.</p>

        {state.projectStatus === "error" && (
          <p
            role="alert"
            className="mt-4 rounded border border-danger/40 bg-danger/10 px-3 py-2 text-xs text-danger"
          >
            Unable to load project. {state.projectError}
          </p>
        )}

        <div className="mt-5 flex flex-col gap-2 sm:flex-row">
          <button type="button" onClick={onNewProject} className={button}>
            <FolderPlus aria-hidden className="size-4 text-accent" />
            New project
          </button>
          <button type="button" onClick={onOpenFolder} className={button}>
            <FolderOpen aria-hidden className="size-4 text-accent" />
            Open folder
          </button>
        </div>

        <p className="mt-5 text-xs leading-relaxed text-fg-subtle">
          {canOpenDirectory
            ? "Opened folders are edited in place: Save writes changes back to disk."
            : "This browser cannot write to local folders, so an opened folder is loaded as a read-only copy and saved changes stay in this tab. Use a Chromium-based browser to edit files on disk."}{" "}
          Files are read in your browser; dependency folders (node_modules, .venv, …) and .env files
          are skipped.
        </p>
      </div>
    </div>
  );
}
