"use client";

import { FolderUp, RefreshCw, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { useConfirm } from "@/components/ui/confirm-dialog";
import { IconButton } from "@/components/ui/icon-button";
import { buttonClass, PageFrame } from "@/components/ui/page-frame";
import { StateMessage } from "@/components/ui/state-message";
import { LanguageList, ProjectStatusBadges } from "@/features/projects/projects-page";
import { selectFolder, type FolderSelection } from "@/features/workspace/folder-upload";
import { UploadFolderDialog } from "@/features/workspace/upload-folder-dialog";
import { GitHubImportPanel } from "./github-import-panel";
import { formatDate, formatRelativeTime, plural } from "@/lib/format";
import { isApiError } from "@/services/api/errors";
import { deleteProject, listProjects, type ServerProject } from "@/services/api/projects";

type ListState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; projects: ServerProject[] };

/**
 * Module 18: folders uploaded from this computer. They are kept apart from the Coding workspace and
 * the Projects list, and are analyzed read-only (search, architecture, impact, questions to the agent).
 */
export function UploadsPage() {
  const router = useRouter();
  const githubResult = useSearchParams().get("github");
  const confirm = useConfirm();
  const inputRef = useRef<HTMLInputElement>(null);
  const [state, setState] = useState<ListState>({ status: "loading" });
  const [selection, setSelection] = useState<FolderSelection | null>(null);

  const load = useCallback(async () => {
    setState({ status: "loading" });
    try {
      setState({ status: "ready", projects: await listProjects({ origin: "upload" }) });
    } catch (error) {
      setState({
        status: "error",
        message: isApiError(error) ? error.message : "Unable to load your uploads.",
      });
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

  // `webkitdirectory` is not in React's input typings; set it on the element.
  useEffect(() => {
    inputRef.current?.setAttribute("webkitdirectory", "");
  }, []);

  const pickFolder = () => inputRef.current?.click();

  const remove = async (project: ServerProject) => {
    const choice = await confirm({
      title: `Delete “${project.name}”?`,
      message:
        "The uploaded copy, its analysis, and its history are deleted from the server. The folder on your computer is not touched.",
      actions: [
        { value: "cancel", label: "Cancel" },
        { value: "delete", label: "Delete upload", variant: "danger" },
      ],
      cancelValue: "cancel",
    });
    if (choice !== "delete") return;
    try {
      await deleteProject(project.id);
    } catch (error) {
      await confirm({
        title: "Delete failed",
        message: isApiError(error) ? error.message : "The upload could not be deleted.",
        actions: [{ value: "ok", label: "OK" }],
        cancelValue: "ok",
      });
    }
    void load();
  };

  const uploadButton = (label: string) => (
    <button type="button" className={buttonClass.primary} onClick={pickFolder}>
      <FolderUp aria-hidden className="size-3.5" />
      {label}
    </button>
  );

  return (
    <PageFrame
      title="Uploads"
      meta={state.status === "ready" ? plural(state.projects.length, "upload") : undefined}
      actions={
        <>
          <IconButton label="Refresh" onClick={() => void load()}>
            <RefreshCw aria-hidden className="size-3.5" />
          </IconButton>
          {uploadButton("Upload folder")}
        </>
      }
    >
      <GitHubImportPanel callbackResult={githubResult} onImported={() => void load()} />
      {state.status === "loading" && <StateMessage title="Loading uploads…" />}
      {state.status === "error" && (
        <StateMessage
          tone="error"
          title="Unable to load uploads"
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
        <StateMessage title="No uploads yet" action={uploadButton("Upload a folder")}>
          Upload a project folder from this computer to analyze it and ask questions about it. It is
          kept separate from your Coding projects, and the agent never changes its files.
        </StateMessage>
      )}
      {state.status === "ready" && state.projects.length > 0 && (
        <ul className="divide-y divide-border">
          {state.projects.map((project) => (
            <li key={project.id} className="flex items-center gap-2 pr-3 hover:bg-surface-hover">
              <Link
                href={`/app/uploads/${project.id}`}
                className="grid min-w-0 flex-1 gap-x-6 gap-y-1 px-4 py-3 focus-visible:bg-surface-hover sm:grid-cols-[minmax(0,1fr)_auto]"
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
                  <dt className="sr-only">Uploaded</dt>
                  <dd className="col-span-2" title={formatDate(project.created_at)}>
                    Uploaded {formatRelativeTime(project.created_at)}
                  </dd>
                </dl>
              </Link>
              <IconButton label={`Delete ${project.name}`} onClick={() => void remove(project)}>
                <Trash2 aria-hidden className="size-4" />
              </IconButton>
            </li>
          ))}
        </ul>
      )}

      <UploadFolderDialog
        selection={selection}
        server={{ available: true }}
        onClose={() => {
          setSelection(null);
          void load();
        }}
        onOpenProject={async (project) => {
          setSelection(null);
          router.push(`/app/uploads/${project.id}`);
        }}
      />
      <input
        ref={inputRef}
        type="file"
        multiple
        hidden
        aria-hidden
        tabIndex={-1}
        onChange={(event) => {
          const files = event.target.files;
          if (files && files.length > 0) setSelection(selectFolder(files));
          event.target.value = "";
        }}
      />
    </PageFrame>
  );
}
