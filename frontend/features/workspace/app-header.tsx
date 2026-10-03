"use client";

import { FolderOpen, FolderPlus, PanelLeft, ScanSearch, X } from "lucide-react";

import { IconButton } from "@/components/ui/icon-button";
import { EditorSettingsMenu } from "@/features/settings/editor-settings-menu";

import { isDirty } from "./state";
import { useWorkspace } from "./workspace-context";

const SOURCE_BADGE = {
  memory: { label: "In memory", title: "New project kept in this browser tab; not persisted." },
  "local-directory": {
    label: "Local folder",
    title: "Opened from disk with write access; Save writes files to disk.",
  },
  server: {
    label: "Server",
    title: "Stored in the CodeWalk database; Save sends changes to the server.",
  },
  "local-snapshot": {
    label: "Read-only copy",
    title:
      "Copy of a local folder. Original files are not modified; saved changes stay in this tab.",
  },
} as const;

interface AppHeaderProps {
  sidebarOpen: boolean;
  onToggleSidebar(): void;
  onNewProject(): void;
  onOpenFolder(): void;
}

export function AppHeader({
  sidebarOpen,
  onToggleSidebar,
  onNewProject,
  onOpenFolder,
}: AppHeaderProps) {
  const { state, actions } = useWorkspace();
  const { project, activePath, buffers, editorSettings } = state;
  const activeDirty = activePath ? isDirty(buffers[activePath]) : false;
  const unsavedCount = Object.values(buffers).filter(isDirty).length;
  const badge = project ? SOURCE_BADGE[project.kind] : null;

  return (
    <header className="flex h-10 shrink-0 items-center gap-2 border-b border-border bg-surface-sunken px-2">
      <IconButton
        label={sidebarOpen ? "Hide explorer" : "Show explorer"}
        shortcut="Ctrl+B"
        active={sidebarOpen}
        onClick={onToggleSidebar}
        disabled={!project}
      >
        <PanelLeft aria-hidden className="size-4" />
      </IconButton>

      <h1 className="pr-1 text-[11px] font-semibold tracking-wider text-fg-muted uppercase">
        Coding
      </h1>

      {project && (
        <nav
          aria-label="Location"
          className="flex min-w-0 flex-1 items-center gap-1.5 text-xs text-fg-muted"
        >
          <span aria-hidden className="text-fg-subtle">
            /
          </span>
          <span className="truncate font-medium text-fg">{project.name}</span>
          {badge && (
            <span
              title={badge.title}
              className="hidden shrink-0 rounded border border-border px-1.5 py-px text-[10px] md:inline"
            >
              {badge.label}
            </span>
          )}
          {activePath && (
            <>
              <span aria-hidden className="text-fg-subtle">
                /
              </span>
              <span className="truncate font-mono" title={activePath}>
                {activePath}
              </span>
              {activeDirty && <span className="shrink-0 text-warning">● unsaved</span>}
            </>
          )}
        </nav>
      )}
      {!project && <span className="flex-1" />}

      <div className="flex shrink-0 items-center gap-0.5">
        {unsavedCount > 0 && (
          <span className="mr-2 hidden text-[11px] text-fg-muted lg:inline">
            {unsavedCount} unsaved file{unsavedCount === 1 ? "" : "s"}
          </span>
        )}
        {project?.serverProjectId && (
          <IconButton
            label="Analyze project"
            onClick={() => void actions.analyzeServerProject()}
            disabled={state.intelligence.status === "loading"}
          >
            <ScanSearch aria-hidden className="size-4" />
          </IconButton>
        )}
        <IconButton label="New project" onClick={onNewProject}>
          <FolderPlus aria-hidden className="size-4" />
        </IconButton>
        <IconButton label="Open folder" onClick={onOpenFolder}>
          <FolderOpen aria-hidden className="size-4" />
        </IconButton>
        {project && (
          <IconButton label="Close project" onClick={() => void actions.closeProject()}>
            <X aria-hidden className="size-4" />
          </IconButton>
        )}
        <span aria-hidden className="mx-1 h-4 w-px bg-border" />
        <EditorSettingsMenu settings={editorSettings} onChange={actions.updateSettings} />
      </div>
    </header>
  );
}
