"use client";

import { ChevronDown, ChevronRight, ChevronsDownUp, FilePlus } from "lucide-react";
import { memo, useCallback, useMemo, useRef, useState, type KeyboardEvent } from "react";

import { IconButton } from "@/components/ui/icon-button";
import { StateMessage } from "@/components/ui/state-message";
import { MAX_PROJECT_ENTRIES } from "@/features/workspace/sources/types";
import { isDirty } from "@/features/workspace/state";
import { useWorkspace } from "@/features/workspace/workspace-context";
import { ancestorPaths, dirname } from "@/lib/project-paths";
import type { ProjectTreeNode } from "@/types/project";

import { FileIcon, FolderIcon } from "./file-icon";
import { NewFileForm } from "./new-file-form";
import { flattenVisible } from "./visible-nodes";

function treeItemId(path: string): string {
  return `tree-${encodeURIComponent(path)}`;
}

interface TreeRowProps {
  node: ProjectTreeNode;
  depth: number;
  expanded: boolean;
  focused: boolean;
  active: boolean;
  dirty: boolean;
  onActivate(node: ProjectTreeNode): void;
  onFocus(path: string): void;
}

const TreeRow = memo(function TreeRow({
  node,
  depth,
  expanded,
  focused,
  active,
  dirty,
  onActivate,
  onFocus,
}: TreeRowProps) {
  const isFolder = node.type === "folder";
  return (
    <div
      id={treeItemId(node.path)}
      role="treeitem"
      aria-level={depth + 1}
      aria-expanded={isFolder ? expanded : undefined}
      aria-selected={active}
      tabIndex={focused ? 0 : -1}
      title={node.path}
      onClick={() => {
        onFocus(node.path);
        onActivate(node);
      }}
      style={{ paddingLeft: `${depth * 12 + 6}px` }}
      className={`flex h-6 cursor-pointer items-center gap-1 pr-2 text-[13px] select-none ${
        active ? "bg-accent-muted text-fg" : "text-fg-muted hover:bg-surface-hover hover:text-fg"
      }`}
    >
      {isFolder ? (
        expanded ? (
          <ChevronDown aria-hidden className="size-3.5 shrink-0" />
        ) : (
          <ChevronRight aria-hidden className="size-3.5 shrink-0" />
        )
      ) : (
        <span aria-hidden className="w-3.5 shrink-0" />
      )}
      {isFolder ? <FolderIcon open={expanded} /> : <FileIcon language={node.language} />}
      <span className="min-w-0 flex-1 truncate">{node.name}</span>
      {dirty && (
        <span aria-label="unsaved changes" className="size-1.5 shrink-0 rounded-full bg-fg-muted" />
      )}
    </div>
  );
});

/** Rendered with `key={project.id}` so all tree UI state resets when another project opens. */
export function ProjectExplorer() {
  const { state, tree, actions } = useWorkspace();
  const { project, projectStatus, projectError, activePath, buffers } = state;
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(new Set());
  const [focusedPath, setFocusedPath] = useState<string | null>(null);
  const [creatingIn, setCreatingIn] = useState<string | null>(null);
  const treeRef = useRef<HTMLDivElement>(null);

  // Keep the active file's folders expanded so it is always visible. (State is
  // adjusted during render when activePath changes, per React's guidance.)
  const [revealedPath, setRevealedPath] = useState<string | null>(null);
  if (activePath !== revealedPath) {
    setRevealedPath(activePath);
    if (activePath) {
      const ancestors = ancestorPaths(activePath);
      if (!ancestors.every((path) => expanded.has(path)))
        setExpanded(new Set([...expanded, ...ancestors]));
    }
  }

  const visible = useMemo(() => (tree ? flattenVisible(tree, expanded) : []), [tree, expanded]);

  const toggleFolder = useCallback(
    (path: string, open?: boolean) =>
      setExpanded((current) => {
        const next = new Set(current);
        if (open ?? !next.has(path)) next.add(path);
        else next.delete(path);
        return next;
      }),
    [],
  );

  // Stable across renders so memoized rows are not all re-rendered on every keystroke in the editor.
  const activate = useCallback(
    (node: ProjectTreeNode) => {
      if (node.type === "folder") toggleFolder(node.path);
      else void actions.openFile(node.path);
    },
    [actions, toggleFolder],
  );

  const focusRow = (path: string) => {
    setFocusedPath(path);
    document.getElementById(treeItemId(path))?.focus();
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (visible.length === 0) return;
    const index = Math.max(
      0,
      visible.findIndex((item) => item.node.path === focusedPath),
    );
    const current = visible[index];
    let handled = true;
    switch (event.key) {
      case "ArrowDown":
        focusRow(visible[Math.min(index + 1, visible.length - 1)].node.path);
        break;
      case "ArrowUp":
        focusRow(visible[Math.max(index - 1, 0)].node.path);
        break;
      case "Home":
        focusRow(visible[0].node.path);
        break;
      case "End":
        focusRow(visible[visible.length - 1].node.path);
        break;
      case "ArrowRight":
        if (current.node.type === "folder") {
          if (!expanded.has(current.node.path)) toggleFolder(current.node.path, true);
          else if (visible[index + 1]?.parentPath === current.node.path)
            focusRow(visible[index + 1].node.path);
        }
        break;
      case "ArrowLeft":
        if (current.node.type === "folder" && expanded.has(current.node.path))
          toggleFolder(current.node.path, false);
        else if (current.parentPath) focusRow(current.parentPath);
        break;
      case "Enter":
      case " ":
        activate(current.node);
        break;
      default:
        handled = false;
    }
    if (handled) event.preventDefault();
  };

  const targetFolder = () => {
    const focused = visible.find((item) => item.node.path === focusedPath)?.node;
    if (!focused) return "";
    return focused.type === "folder" ? focused.path : dirname(focused.path);
  };

  let content: React.ReactNode;
  if (projectStatus === "loading") {
    content = <StateMessage title="Loading project…" />;
  } else if (projectStatus === "error") {
    content = (
      <StateMessage tone="error" title="Unable to load project.">
        {projectError}
      </StateMessage>
    );
  } else if (!project || !tree) {
    content = (
      <StateMessage title="No project open">
        Create a project or open a folder to get started.
      </StateMessage>
    );
  } else if (tree.children.length === 0 && creatingIn === null) {
    content = (
      <StateMessage
        title="No files in this project."
        action={
          <button
            type="button"
            onClick={() => setCreatingIn("")}
            className="mt-1 rounded border border-border px-2 py-1 text-xs hover:bg-surface-hover"
          >
            New file
          </button>
        }
      />
    );
  } else {
    const rovingPath = focusedPath ?? activePath ?? visible[0]?.node.path;
    content = (
      <div
        ref={treeRef}
        role="tree"
        aria-label={`Files in ${project.name}`}
        onKeyDown={handleKeyDown}
        className="min-h-0 flex-1 overflow-auto py-1"
      >
        {visible.map(({ node, depth }) => (
          <TreeRow
            key={node.path}
            node={node}
            depth={depth}
            expanded={expanded.has(node.path)}
            focused={node.path === rovingPath}
            active={node.path === activePath}
            dirty={node.type === "file" && isDirty(buffers[node.path])}
            onActivate={activate}
            onFocus={setFocusedPath}
          />
        ))}
      </div>
    );
  }

  return (
    <aside aria-label="Project explorer" className="flex h-full min-w-0 flex-col bg-surface-sunken">
      <div className="flex h-9 shrink-0 items-center gap-1 border-b border-border pr-1 pl-3">
        <h2 className="min-w-0 flex-1 truncate text-[11px] font-semibold tracking-wider text-fg-muted uppercase">
          {project ? project.name : "Explorer"}
        </h2>
        {project && projectStatus === "ready" && (
          <>
            <IconButton label="New file" onClick={() => setCreatingIn(targetFolder())}>
              <FilePlus aria-hidden className="size-4" />
            </IconButton>
            <IconButton
              label="Collapse all folders"
              onClick={() => setExpanded(new Set())}
              disabled={expanded.size === 0}
            >
              <ChevronsDownUp aria-hidden className="size-4" />
            </IconButton>
          </>
        )}
      </div>
      {creatingIn !== null && (
        <NewFileForm
          parentPath={creatingIn}
          onCreate={actions.createFile}
          onDone={() => setCreatingIn(null)}
        />
      )}
      {content}
      {project && (project.skippedEntries > 0 || project.truncated) && (
        <p className="shrink-0 border-t border-border px-3 py-1.5 text-[11px] text-fg-subtle">
          {project.truncated
            ? `Large project: only the first ${MAX_PROJECT_ENTRIES.toLocaleString()} entries are shown.`
            : `${project.skippedEntries} ignored item${project.skippedEntries === 1 ? "" : "s"} (dependencies, build output, secrets).`}
        </p>
      )}
    </aside>
  );
}
