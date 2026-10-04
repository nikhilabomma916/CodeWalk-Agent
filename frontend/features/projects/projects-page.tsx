"use client";

import { FolderPlus, FolderUp, Link2, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { IconButton } from "@/components/ui/icon-button";
import { buttonClass, PageFrame } from "@/components/ui/page-frame";
import { StateMessage } from "@/components/ui/state-message";
import { NewProjectDialog, type NewProjectRequest } from "@/features/workspace/new-project-dialog";
import { backendLanguageLabel, formatDate, formatRelativeTime, plural } from "@/lib/format";
import { isApiError } from "@/services/api/errors";
import { analyzeProject } from "@/services/api/intelligence";
import {
  createProject,
  getWorkspaceFolders,
  listProjects,
  type ServerProject,
} from "@/services/api/projects";

type ListState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; projects: ServerProject[]; workspaceFolders: string[] | null };

function errorMessage(error: unknown, fallback: string): string {
  return isApiError(error) ? error.message : fallback;
}

/** Uploaded folders open in their read-only analysis view; workspace projects in Projects. */
export function projectHref(project: ServerProject): string {
  return project.origin === "upload" ? `/app/uploads/${project.id}` : `/app/projects/${project.id}`;
}

export function ProjectStatusBadges({ project }: { project: ServerProject }) {
  const badge = "rounded border px-1.5 py-px text-[10px] leading-4";
  return (
    <>
      {project.read_only && (
        <span
          className={`${badge} border-border text-fg-muted`}
          title={`Linked to server folder ${project.root_path}; files come from scanning and are read-only.`}
        >
          <Link2 aria-hidden className="mr-0.5 inline size-3 align-[-2px]" />
          Linked folder
        </span>
      )}
      {project.origin === "upload" && (
        <span
          className={`${badge} border-accent/50 text-accent-text`}
          title="Uploaded from a local folder; analyzed read-only in Uploads."
        >
          <FolderUp aria-hidden className="mr-0.5 inline size-3 align-[-2px]" />
          Uploaded
        </span>
      )}
      {project.stats.last_analyzed_at ? (
        <span
          className={`${badge} border-success/40 text-success`}
          title={`Project analysis ran ${formatDate(project.stats.last_analyzed_at)}`}
        >
          Analyzed {formatRelativeTime(project.stats.last_analyzed_at)}
        </span>
      ) : (
        <span className={`${badge} border-border text-fg-subtle`}>Not analyzed</span>
      )}
    </>
  );
}

export function LanguageList({ project, max = 3 }: { project: ServerProject; max?: number }) {
  const { languages } = project.stats;
  if (languages.length === 0) return <span className="text-fg-subtle">No files</span>;
  const shown = languages.slice(0, max);
  return (
    <span
      title={languages.map((l) => `${backendLanguageLabel(l.language)}: ${l.files}`).join(", ")}
    >
      {shown.map((l) => backendLanguageLabel(l.language)).join(" · ")}
      {languages.length > max && ` +${languages.length - max}`}
    </span>
  );
}

export function ProjectsPage() {
  const router = useRouter();
  const [state, setState] = useState<ListState>({ status: "loading" });
  const [dialogOpen, setDialogOpen] = useState(false);

  const load = useCallback(async () => {
    setState({ status: "loading" });
    try {
      const [projects, workspace] = await Promise.all([
        listProjects(), // workspace projects and folders uploaded from this computer
        getWorkspaceFolders(),
      ]);
      setState({
        status: "ready",
        projects,
        workspaceFolders: workspace.enabled ? workspace.folders : null,
      });
    } catch (error) {
      setState({ status: "error", message: errorMessage(error, "Unable to load your projects.") });
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    void Promise.resolve().then(() => {
      if (!cancelled) void load();
    });
    return () => {
      cancelled = true;
    };
  }, [load]);

  const handleCreate = useCallback(
    async (request: NewProjectRequest): Promise<string | null> => {
      try {
        const project = await createProject({
          name: request.name,
          description: request.description,
          rootPath: request.rootPath,
        });
        if (project.root_path) await analyzeProject(project.id); // import the linked folder's files
        setDialogOpen(false);
        router.push(`/app/projects/${project.id}`);
        return null;
      } catch (error) {
        return errorMessage(error, "The project could not be created.");
      }
    },
    [router],
  );

  const count = state.status === "ready" ? state.projects.length : null;

  return (
    <PageFrame
      title="Projects"
      meta={count !== null ? plural(count, "project") : undefined}
      actions={
        <>
          <IconButton label="Refresh" onClick={() => void load()}>
            <RefreshCw aria-hidden className="size-3.5" />
          </IconButton>
          <button type="button" className={buttonClass.primary} onClick={() => setDialogOpen(true)}>
            <FolderPlus aria-hidden className="size-3.5" />
            New project
          </button>
        </>
      }
    >
      {state.status === "loading" && <StateMessage title="Loading projects…" />}
      {state.status === "error" && (
        <StateMessage
          tone="error"
          title="Unable to load projects"
          action={
            <button type="button" className={buttonClass.secondary} onClick={() => void load()}>
              Try again
            </button>
          }
        >
          {state.message}
        </StateMessage>
      )}
      {state.status === "ready" && state.projects.length === 0 && (
        <StateMessage
          title="No projects yet"
          action={
            <button
              type="button"
              className={buttonClass.primary}
              onClick={() => setDialogOpen(true)}
            >
              <FolderPlus aria-hidden className="size-3.5" />
              Create your first project
            </button>
          }
        >
          Projects keep your files on the server, with saved versions, analysis, and history.
        </StateMessage>
      )}
      {state.status === "ready" && state.projects.length > 0 && (
        <ul className="divide-y divide-border">
          {state.projects.map((project) => (
            <li key={project.id}>
              <Link
                href={projectHref(project)}
                className="grid gap-x-6 gap-y-1 px-4 py-3 hover:bg-surface-hover focus-visible:bg-surface-hover sm:grid-cols-[minmax(0,1fr)_auto]"
              >
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="truncate text-sm font-medium text-fg">{project.name}</span>
                    <ProjectStatusBadges project={project} />
                  </div>
                  <p className="mt-0.5 truncate text-xs text-fg-muted">
                    {project.description || <span className="text-fg-subtle">No description</span>}
                  </p>
                </div>
                <dl className="grid grid-cols-[auto_auto] gap-x-3 text-[11px] text-fg-muted sm:text-right">
                  <dt className="sr-only">Files</dt>
                  <dd className="col-span-2 text-fg">
                    {plural(project.stats.file_count, "file")} ·{" "}
                    {plural(project.stats.total_lines, "line")}
                  </dd>
                  <dt className="sr-only">Languages</dt>
                  <dd className="col-span-2">
                    <LanguageList project={project} />
                  </dd>
                  <dt className="sr-only">Updated</dt>
                  <dd className="col-span-2" title={formatDate(project.updated_at)}>
                    Updated {formatRelativeTime(project.updated_at)} · created{" "}
                    {formatDate(project.created_at)}
                  </dd>
                </dl>
              </Link>
            </li>
          ))}
        </ul>
      )}

      <NewProjectDialog
        open={dialogOpen}
        server={{ available: true }}
        allowBrowserStorage={false}
        workspaceFolders={state.status === "ready" ? state.workspaceFolders : null}
        onClose={() => setDialogOpen(false)}
        onCreate={handleCreate}
      />
    </PageFrame>
  );
}
