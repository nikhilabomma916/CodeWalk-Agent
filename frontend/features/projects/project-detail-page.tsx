"use client";

import {
  ChevronDown,
  ChevronRight,
  Code2,
  History,
  Pencil,
  ScanSearch,
  Trash2,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";

import { useConfirm } from "@/components/ui/confirm-dialog";
import { buttonClass, PageFrame } from "@/components/ui/page-frame";
import { StateMessage } from "@/components/ui/state-message";
import { ProjectAsk, type AskModeOption } from "@/features/agent/project-ask";
import { ProjectExplain } from "@/features/agent/project-explain";
import { codingHref } from "@/features/workspace/use-coding-deep-link";
import { useWorkspace } from "@/features/workspace/workspace-context";
import {
  backendLanguageLabel,
  formatBytes,
  formatDateTime,
  formatRelativeTime,
  plural,
} from "@/lib/format";
import { isApiError } from "@/services/api/errors";
import {
  analyzeProject,
  getProjectIntelligence,
  type ProjectIntelligence,
} from "@/services/api/intelligence";
import {
  deleteProject,
  getProject,
  listFiles,
  updateProject,
  type ServerFile,
  type ServerProject,
} from "@/services/api/projects";

import { ProjectFileTree } from "./project-file-tree";
import { ProjectStatusBadges } from "./projects-page";

const PROJECT_ASK_MODES: readonly AskModeOption[] = [
  { id: "assist", label: "Ask a question" },
  { id: "architecture", label: "Explain the architecture" },
  { id: "impact", label: "What could break?" },
];

type DetailState =
  | { status: "loading" }
  | { status: "not-found" }
  | { status: "error"; message: string }
  | {
      status: "ready";
      project: ServerProject;
      files: ServerFile[];
      intelligence: ProjectIntelligence | null;
    };

function errorMessage(error: unknown, fallback: string): string {
  return isApiError(error) ? error.message : fallback;
}

function Stat({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-[10px] tracking-wider text-fg-subtle uppercase">{label}</dt>
      <dd className="mt-0.5 truncate text-sm text-fg">{children}</dd>
    </div>
  );
}

function EditProjectDialog({
  project,
  open,
  onClose,
  onSaved,
}: {
  project: ServerProject;
  open: boolean;
  onClose(): void;
  onSaved(project: ServerProject): void;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [name, setName] = useState(project.name);
  const [description, setDescription] = useState(project.description ?? "");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    else if (!open && dialog.open) dialog.close();
  }, [open]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) return setError("Enter a project name.");
    if (trimmed.length > 100) return setError("Use at most 100 characters.");
    if (/[\\/]/.test(trimmed)) return setError("Project names cannot contain slashes.");
    setBusy(true);
    try {
      onSaved(
        await updateProject(project.id, {
          name: trimmed,
          description: description.trim() || null,
        }),
      );
    } catch (cause) {
      setError(errorMessage(cause, "The project could not be updated."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <dialog
      ref={dialogRef}
      aria-labelledby="edit-project-title"
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      className="m-auto w-[min(28rem,calc(100vw-2rem))] rounded-md border border-border bg-surface p-0 text-fg shadow-xl backdrop:bg-black/60"
    >
      <form onSubmit={submit}>
        <div className="space-y-3 p-4">
          <h2 id="edit-project-title" className="text-sm font-semibold">
            Edit project
          </h2>
          <div>
            <label htmlFor="edit-project-name" className="block text-xs text-fg-muted">
              Project name
            </label>
            <input
              id="edit-project-name"
              value={name}
              disabled={busy}
              onChange={(event) => {
                setName(event.target.value);
                setError(null);
              }}
              className="mt-1 w-full rounded border border-border bg-surface-sunken px-2 py-1.5 text-sm outline-none focus:border-accent"
            />
          </div>
          <div>
            <label htmlFor="edit-project-description" className="block text-xs text-fg-muted">
              Description
            </label>
            <textarea
              id="edit-project-description"
              value={description}
              disabled={busy}
              rows={3}
              maxLength={2000}
              onChange={(event) => setDescription(event.target.value)}
              className="mt-1 w-full resize-y rounded border border-border bg-surface-sunken px-2 py-1.5 text-sm outline-none focus:border-accent"
            />
          </div>
          {error && (
            <p role="alert" className="text-xs text-danger">
              {error}
            </p>
          )}
        </div>
        <div className="flex justify-end gap-2 border-t border-border bg-surface-sunken px-4 py-3">
          <button type="button" className={buttonClass.secondary} onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className={buttonClass.primary} disabled={busy}>
            {busy ? "Saving…" : "Save"}
          </button>
        </div>
      </form>
    </dialog>
  );
}

export function ProjectDetailPage({ projectId }: { projectId: string }) {
  const router = useRouter();
  const confirm = useConfirm();
  const { state: workspace, actions } = useWorkspace();
  const [state, setState] = useState<DetailState>({ status: "loading" });
  const [analyzing, setAnalyzing] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  // Details are shown on request: the page answers questions instead of listing everything up front.
  const [showDetails, setShowDetails] = useState(false);

  const load = useCallback(async () => {
    try {
      const [project, files, intelligence] = await Promise.all([
        getProject(projectId),
        listFiles(projectId),
        getProjectIntelligence(projectId),
      ]);
      setState({ status: "ready", project, files, intelligence });
    } catch (error) {
      if (isApiError(error) && (error.status === 404 || error.status === 422)) {
        setState({ status: "not-found" });
      } else {
        setState({ status: "error", message: errorMessage(error, "Unable to load the project.") });
      }
    }
  }, [projectId]);

  useEffect(() => {
    let cancelled = false;
    void Promise.resolve().then(() => {
      if (!cancelled) void load();
    });
    return () => {
      cancelled = true;
    };
  }, [load]);

  const analyze = async () => {
    setAnalyzing(true);
    setActionError(null);
    try {
      await analyzeProject(projectId);
      await load();
    } catch (error) {
      setActionError(errorMessage(error, "Project analysis failed."));
    } finally {
      setAnalyzing(false);
    }
  };

  const remove = async (project: ServerProject) => {
    const choice = await confirm({
      title: `Delete “${project.name}”?`,
      message: project.root_path
        ? "The project record, its analyses, and saved versions are deleted. Files in the linked folder are not touched. History entries are kept."
        : "The project, its files, saved versions, and analyses are permanently deleted. History entries are kept.",
      actions: [
        { value: "cancel", label: "Cancel" },
        { value: "delete", label: "Delete project", variant: "danger" },
      ],
      cancelValue: "cancel",
    });
    if (choice !== "delete") return;
    // If the project is open in Coding, close it first (asks about unsaved changes).
    if (workspace.project?.serverProjectId === project.id && !(await actions.closeProject()))
      return;
    try {
      await deleteProject(project.id);
      router.push("/app/projects");
    } catch (error) {
      setActionError(errorMessage(error, "The project could not be deleted."));
    }
  };

  if (state.status === "loading") {
    return (
      <PageFrame title={<Link href="/app/projects">Projects</Link>}>
        <StateMessage title="Loading project…" />
      </PageFrame>
    );
  }
  if (state.status === "not-found") {
    return (
      <PageFrame title={<Link href="/app/projects">Projects</Link>}>
        <StateMessage
          title="Project not found"
          action={
            <Link href="/app/projects" className={buttonClass.secondary}>
              Back to projects
            </Link>
          }
        >
          It may have been deleted, or it belongs to another account.
        </StateMessage>
      </PageFrame>
    );
  }
  if (state.status === "error") {
    return (
      <PageFrame title={<Link href="/app/projects">Projects</Link>}>
        <StateMessage
          tone="error"
          title="Unable to load the project"
          action={
            <button type="button" className={buttonClass.secondary} onClick={() => void load()}>
              Try again
            </button>
          }
        >
          {state.message}
        </StateMessage>
      </PageFrame>
    );
  }

  const { project, files, intelligence } = state;
  const stats = project.stats;

  return (
    <PageFrame
      title={
        <Link href="/app/projects" className="hover:text-fg">
          Projects
        </Link>
      }
      meta={
        <>
          <span aria-hidden className="mr-1.5 text-fg-subtle">
            /
          </span>
          <span className="text-fg">{project.name}</span>
        </>
      }
      actions={
        <>
          <Link href={`/app/history?project=${project.id}`} className={buttonClass.secondary}>
            <History aria-hidden className="size-3.5" />
            <span className="hidden sm:inline">History</span>
          </Link>
          <button
            type="button"
            className={buttonClass.secondary}
            onClick={() => void analyze()}
            disabled={analyzing}
          >
            <ScanSearch aria-hidden className={`size-3.5 ${analyzing ? "animate-pulse" : ""}`} />
            <span className="hidden sm:inline">{analyzing ? "Analyzing…" : "Analyze"}</span>
          </button>
          <Link
            href={
              project.origin === "upload" ? `/app/uploads/${project.id}` : codingHref(project.id)
            }
            className={buttonClass.primary}
          >
            <Code2 aria-hidden className="size-3.5" />
            {project.origin === "upload" ? "Open analysis" : "Open in Coding"}
          </Link>
        </>
      }
    >
      <div className="mx-auto max-w-6xl space-y-5 p-4">
        <section aria-labelledby="project-title" className="space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <h2 id="project-title" className="text-lg font-semibold text-fg">
              {project.name}
            </h2>
            <ProjectStatusBadges project={project} />
            <span className="flex-1" />
            <button
              type="button"
              className={buttonClass.secondary}
              onClick={() => setEditing(true)}
            >
              <Pencil aria-hidden className="size-3.5" />
              Edit
            </button>
            <button
              type="button"
              className={buttonClass.danger}
              onClick={() => void remove(project)}
            >
              <Trash2 aria-hidden className="size-3.5" />
              Delete
            </button>
          </div>
          <p className="max-w-3xl text-sm whitespace-pre-line text-fg-muted">
            {project.description || <span className="text-fg-subtle">No description.</span>}
          </p>
          {actionError && (
            <p role="alert" className="text-xs text-danger">
              {actionError}
            </p>
          )}
        </section>

        <section aria-labelledby="ask-title" className="rounded border border-border p-3">
          <h3
            id="ask-title"
            className="mb-2 text-[11px] font-semibold tracking-wider text-fg-muted uppercase"
          >
            Ask about this project
          </h3>
          <ProjectAsk
            projectId={project.id}
            modes={PROJECT_ASK_MODES}
            placeholder="e.g. What have we done in this project? How does authentication work?"
            onOpen={(path, line) => router.push(codingHref(project.id, path, line))}
          />
        </section>

        <section aria-labelledby="explain-title" className="rounded border border-border p-3">
          <h3
            id="explain-title"
            className="mb-2 text-[11px] font-semibold tracking-wider text-fg-muted uppercase"
          >
            Project explanation
          </h3>
          <ProjectExplain
            projectId={project.id}
            onOpen={(path, line) => router.push(codingHref(project.id, path, line))}
          />
        </section>

        <button
          type="button"
          aria-expanded={showDetails}
          aria-controls="project-details"
          onClick={() => setShowDetails((open) => !open)}
          className={buttonClass.secondary}
        >
          {showDetails ? (
            <ChevronDown aria-hidden className="size-3.5" />
          ) : (
            <ChevronRight aria-hidden className="size-3.5" />
          )}
          {showDetails ? "Hide project details" : "Show project details"}
        </button>

        {showDetails && (
          <div id="project-details" className="space-y-5">
            <dl className="grid grid-cols-2 gap-4 rounded border border-border bg-surface-sunken p-3 sm:grid-cols-3 lg:grid-cols-6">
              <Stat label="Files">{stats.file_count.toLocaleString()}</Stat>
              <Stat label="Lines">{stats.total_lines.toLocaleString()}</Stat>
              <Stat label="Size">{formatBytes(stats.total_bytes)}</Stat>
              <Stat label="Symbols">
                {intelligence ? intelligence.statistics.total_symbols.toLocaleString() : "—"}
              </Stat>
              <Stat label="Last analysis">
                {stats.last_analyzed_at ? (
                  <span title={formatDateTime(stats.last_analyzed_at)}>
                    {formatRelativeTime(stats.last_analyzed_at)}
                  </span>
                ) : (
                  "Never"
                )}
              </Stat>
              <Stat label="Updated">
                <span title={formatDateTime(project.updated_at)}>
                  {formatRelativeTime(project.updated_at)}
                </span>
              </Stat>
            </dl>

            <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
              <section aria-labelledby="explorer-title" className="rounded border border-border">
                <h3
                  id="explorer-title"
                  className="border-b border-border px-3 py-2 text-[11px] font-semibold tracking-wider text-fg-muted uppercase"
                >
                  Explorer
                </h3>
                <ProjectFileTree
                  projectId={project.id}
                  projectName={project.name}
                  files={files}
                  intelligence={intelligence}
                />
                {!intelligence && files.length > 0 && (
                  <p className="border-t border-border px-3 py-2 text-[11px] text-fg-subtle">
                    Analyze the project to list symbols for each file.
                  </p>
                )}
              </section>

              <div className="space-y-4">
                <section aria-labelledby="languages-title" className="rounded border border-border">
                  <h3
                    id="languages-title"
                    className="border-b border-border px-3 py-2 text-[11px] font-semibold tracking-wider text-fg-muted uppercase"
                  >
                    Languages
                  </h3>
                  {stats.languages.length === 0 ? (
                    <p className="px-3 py-3 text-xs text-fg-muted">No files yet.</p>
                  ) : (
                    <ul className="space-y-1.5 px-3 py-2.5 text-xs">
                      {stats.languages.map((language) => (
                        <li key={language.language} className="flex items-center gap-2">
                          <span className="w-24 shrink-0 truncate text-fg">
                            {backendLanguageLabel(language.language)}
                          </span>
                          <span className="h-1.5 flex-1 overflow-hidden rounded bg-surface-raised">
                            <span
                              className="block h-full rounded bg-accent"
                              style={{ width: `${(language.files / stats.file_count) * 100}%` }}
                            />
                          </span>
                          <span className="w-14 shrink-0 text-right text-fg-muted">
                            {plural(language.files, "file")}
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                </section>

                <section aria-labelledby="details-title" className="rounded border border-border">
                  <h3
                    id="details-title"
                    className="border-b border-border px-3 py-2 text-[11px] font-semibold tracking-wider text-fg-muted uppercase"
                  >
                    Details
                  </h3>
                  <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 px-3 py-2.5 text-xs">
                    <dt className="text-fg-subtle">Created</dt>
                    <dd className="text-fg-muted">{formatDateTime(project.created_at)}</dd>
                    <dt className="text-fg-subtle">Storage</dt>
                    <dd className="text-fg-muted">
                      {project.root_path
                        ? `Linked server folder “${project.root_path}”`
                        : "Database"}
                    </dd>
                    {intelligence && (
                      <>
                        <dt className="text-fg-subtle">Imports</dt>
                        <dd className="text-fg-muted">
                          {intelligence.statistics.internal_imports} internal ·{" "}
                          {intelligence.statistics.external_imports} external
                        </dd>
                        <dt className="text-fg-subtle">Analysis errors</dt>
                        <dd
                          className={intelligence.errors.length ? "text-warning" : "text-fg-muted"}
                        >
                          {intelligence.errors.length === 0
                            ? "None"
                            : intelligence.errors.slice(0, 5).map((e) => (
                                <span
                                  key={`${e.path}-${e.stage}`}
                                  className="block truncate"
                                  title={e.message}
                                >
                                  {e.path}: {e.message}
                                </span>
                              ))}
                        </dd>
                      </>
                    )}
                  </dl>
                </section>
              </div>
            </div>
          </div>
        )}
      </div>

      {editing && (
        <EditProjectDialog
          project={project}
          open={editing}
          onClose={() => setEditing(false)}
          onSaved={(updated) => {
            setEditing(false);
            setState({ ...state, project: updated });
          }}
        />
      )}
    </PageFrame>
  );
}
