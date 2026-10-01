"use client";

import { Database, FolderOpen, FolderPlus, RefreshCw, Trash2 } from "lucide-react";

import { useConfirm } from "@/components/ui/confirm-dialog";
import { IconButton } from "@/components/ui/icon-button";
import { StateMessage } from "@/components/ui/state-message";
import { isApiError } from "@/services/api/errors";
import { deleteProject, type ServerProject } from "@/services/api/projects";

import type { ServerProjectsState } from "./use-server-projects";
import { useWorkspace } from "./workspace-context";

interface WelcomeProps {
  onNewProject(): void;
  onOpenFolder(): void;
  serverProjects: ServerProjectsState;
  onRefreshServerProjects(): void;
}

function ServerProjectList({
  state,
  onOpen,
  onRefresh,
}: {
  state: ServerProjectsState;
  onOpen(project: ServerProject): void;
  onRefresh(): void;
}) {
  const confirm = useConfirm();

  const remove = async (project: ServerProject) => {
    const choice = await confirm({
      title: `Delete “${project.name}”?`,
      message: project.root_path
        ? "The project record and its analysis history are deleted. Files in the linked folder are not touched."
        : "The project, its files, and its analysis history are permanently deleted from the server.",
      actions: [
        { value: "cancel", label: "Cancel" },
        { value: "delete", label: "Delete project", variant: "danger" },
      ],
      cancelValue: "cancel",
    });
    if (choice !== "delete") return;
    try {
      await deleteProject(project.id);
    } catch (error) {
      await confirm({
        title: "Delete failed",
        message: isApiError(error) ? error.message : "The project could not be deleted.",
        actions: [{ value: "ok", label: "OK" }],
        cancelValue: "ok",
      });
    }
    onRefresh();
  };

  if (state.status === "unavailable") {
    return <p className="text-xs text-fg-muted">Server projects are unavailable: {state.reason}</p>;
  }
  if (state.status === "loading") return <p className="text-xs text-fg-muted">Loading projects…</p>;
  if (state.status === "error") {
    return (
      <p role="alert" className="text-xs text-danger">
        Unable to load projects. {state.message}
      </p>
    );
  }
  if (state.projects.length === 0) {
    return (
      <p className="text-xs text-fg-muted">
        No server projects yet. Create one with “New project”.
      </p>
    );
  }
  return (
    <ul className="divide-y divide-border rounded border border-border">
      {state.projects.map((project) => (
        <li key={project.id} className="flex items-center gap-2 px-3 py-2">
          <button
            type="button"
            onClick={() => onOpen(project)}
            className="min-w-0 flex-1 text-left"
            title={`Open ${project.name}`}
          >
            <span className="block truncate text-sm text-fg hover:underline">{project.name}</span>
            <span className="block truncate text-[11px] text-fg-muted">
              {project.root_path ? `Linked folder: ${project.root_path} · ` : ""}
              Updated {new Date(project.updated_at).toLocaleString()}
            </span>
          </button>
          <IconButton label={`Delete ${project.name}`} onClick={() => void remove(project)}>
            <Trash2 aria-hidden className="size-4" />
          </IconButton>
        </li>
      ))}
    </ul>
  );
}

export function Welcome({
  onNewProject,
  onOpenFolder,
  serverProjects,
  onRefreshServerProjects,
}: WelcomeProps) {
  const { state, actions, canOpenDirectory } = useWorkspace();

  if (state.projectStatus === "loading") return <StateMessage title="Loading project…" />;

  const button =
    "flex items-center gap-2 rounded border border-border bg-surface-raised px-3 py-2 text-sm text-fg hover:border-border-strong hover:bg-surface-hover";

  return (
    <div className="flex h-full justify-center overflow-auto bg-surface p-6">
      <div className="my-auto w-full max-w-lg">
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
            Open local folder
          </button>
        </div>

        <section aria-label="Server projects" className="mt-6">
          <div className="mb-2 flex items-center gap-2">
            <Database aria-hidden className="size-4 text-fg-muted" />
            <h2 className="flex-1 text-xs font-semibold tracking-wider text-fg-muted uppercase">
              Server projects
            </h2>
            {serverProjects.status !== "unavailable" && (
              <IconButton label="Refresh server projects" onClick={onRefreshServerProjects}>
                <RefreshCw aria-hidden className="size-3.5" />
              </IconButton>
            )}
          </div>
          <ServerProjectList
            state={serverProjects}
            onOpen={(project) => void actions.openServerProject(project)}
            onRefresh={onRefreshServerProjects}
          />
        </section>

        <p className="mt-6 text-xs leading-relaxed text-fg-subtle">
          {canOpenDirectory
            ? "Local folders are edited in place: Save writes changes back to disk."
            : "This browser cannot write to local folders, so a local folder is loaded as a read-only copy and saved changes stay in this tab."}{" "}
          Local folders are read in your browser; dependency folders and .env files are skipped.
        </p>
      </div>
    </div>
  );
}
