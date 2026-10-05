"use client";

import { ChevronDown, ChevronRight, ChevronsDownUp, FilePlus, FolderPlus } from "lucide-react";
import {
  memo,
  useCallback,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type MouseEvent,
} from "react";

import { IconButton } from "@/components/ui/icon-button";
import { StateMessage } from "@/components/ui/state-message";
import { MAX_PROJECT_ENTRIES } from "@/features/workspace/sources/types";
import { isDirty } from "@/features/workspace/state";
import { useWorkspace } from "@/features/workspace/workspace-context";
import { ancestorPaths } from "@/lib/project-paths";
import type { ProjectTreeNode } from "@/types/project";

import { FileIcon, FolderIcon } from "./file-icon";
import { CodeFileDialog } from "./code-file-dialog";
import { ContextMenu, type MenuItem } from "./context-menu";
import { PathDialog, type PathDialogRequest } from "./path-dialog";
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
  onContextMenu(node: ProjectTreeNode, event: MouseEvent<HTMLDivElement>): void;
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
  onContextMenu,
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
      onContextMenu={(event) => {
        event.preventDefault();
        event.stopPropagation();
        onFocus(node.path);
        onContextMenu(node, event);
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
  const { state, tree, actions, fileOperations } = useWorkspace();
  const { project, projectStatus, projectError, activePath, buffers } = state;
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(new Set());
  const [focusedPath, setFocusedPath] = useState<string | null>(null);
  const [creatingFile, setCreatingFile] = useState(false);
  const [dialog, setDialog] = useState<PathDialogRequest | null>(null);
  const [menu, setMenu] = useState<{
    node: ProjectTreeNode | null;
    x: number;
    y: number;
    returnFocus: HTMLElement | null;
  } | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
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

  const openMenu = useCallback(
    (node: ProjectTreeNode | null, x: number, y: number, returnFocus: HTMLElement | null) =>
      setMenu({ node, x, y, returnFocus }),
    [],
  );
  const onRowContextMenu = useCallback(
    (node: ProjectTreeNode, event: MouseEvent<HTMLDivElement>) =>
      openMenu(node, event.clientX, event.clientY, event.currentTarget),
    [openMenu],
  );

  const folderOf = (node: ProjectTreeNode | null) =>
    !node
      ? ""
      : node.type === "folder"
        ? `${node.path}/`
        : node.path.slice(0, node.path.lastIndexOf("/") + 1);

  const newFile = (node: ProjectTreeNode | null) =>
    setDialog({
      title: "New file",
      label: "Path",
      initial: folderOf(node),
      submitLabel: "Create",
      hint: "Folders in the path are created as needed.",
      onSubmit: async (path) => {
        await actions.createFile(path);
        setExpanded((current) => new Set([...current, ...ancestorPaths(path)]));
      },
    });
  const newFolder = (node: ProjectTreeNode | null) =>
    setDialog({
      title: "New folder",
      label: "Folder path",
      initial: folderOf(node),
      submitLabel: "Create",
      hint: "Stored with a .gitkeep file, so the empty folder is kept.",
      onSubmit: async (path) => {
        await actions.createFolder(path);
        setExpanded((current) => new Set([...current, ...ancestorPaths(`${path}/x`)]));
      },
    });
  const rename = (node: ProjectTreeNode, move: boolean) =>
    setDialog({
      title: move ? `Move ${node.name}` : `Rename ${node.name}`,
      label: move ? "New path" : "New name or path",
      initial: node.path,
      submitLabel: move ? "Move" : "Rename",
      hint:
        node.type === "folder"
          ? "Everything in the folder moves with it; open files follow and keep unsaved edits."
          : "Open tabs follow the file and keep unsaved edits.",
      onSubmit: async (path) => {
        await actions.renamePath(node.path, path);
        setExpanded((current) => new Set([...current, ...ancestorPaths(path)]));
      },
    });
  const copyPath = async (path: string) => {
    try {
      await navigator.clipboard.writeText(path);
      setNotice(`Copied ${path}`);
    } catch {
      setNotice("The path could not be copied (clipboard access was denied).");
    }
  };
  const run = (work: Promise<unknown>) =>
    void work.catch((error: unknown) =>
      setNotice(error instanceof Error ? error.message : "The operation failed."),
    );

  const menuItems = (node: ProjectTreeNode | null): MenuItem[] => {
    const off = !fileOperations.enabled;
    const reason = fileOperations.reason;
    const items: MenuItem[] = [];
    if (node?.type === "file")
      items.push({ label: "Open", onSelect: () => void actions.openFile(node.path) });
    items.push(
      {
        label: "New File…",
        onSelect: () => newFile(node),
        disabled: off,
        reason,
        separatorBefore: !!node,
      },
      { label: "New Folder…", onSelect: () => newFolder(node), disabled: off, reason },
    );
    if (node) {
      items.push(
        {
          label: "Rename…",
          onSelect: () => rename(node, false),
          disabled: off,
          reason,
          separatorBefore: true,
          shortcut: "F2",
        },
        { label: "Move…", onSelect: () => rename(node, true), disabled: off, reason },
      );
      if (node.type === "file")
        items.push({
          label: "Duplicate",
          onSelect: () => run(actions.duplicateFile(node.path)),
          disabled: off,
          reason,
        });
      items.push(
        { label: "Copy Path", onSelect: () => void copyPath(node.path), separatorBefore: true },
        {
          label: "Delete…",
          onSelect: () => run(actions.deletePath(node.path)),
          disabled: off,
          reason,
          danger: true,
          separatorBefore: true,
          shortcut: "Del",
        },
      );
    }
    return items;
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
      case "ContextMenu":
      case "F10": {
        if (event.key === "F10" && !event.shiftKey) {
          handled = false;
          break;
        }
        const row = document.getElementById(treeItemId(current.node.path));
        const rect = row?.getBoundingClientRect();
        openMenu(current.node, (rect?.left ?? 0) + 24, rect?.bottom ?? 0, row);
        break;
      }
      case "F2":
        if (fileOperations.enabled) rename(current.node, false);
        else handled = false;
        break;
      case "Delete":
        if (fileOperations.enabled) run(actions.deletePath(current.node.path));
        else handled = false;
        break;
      default:
        handled = false;
    }
    if (handled) event.preventDefault();
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
  } else if (tree.children.length === 0) {
    content = (
      <StateMessage
        title="No files in this project."
        action={
          <button
            type="button"
            onClick={() => setCreatingFile(true)}
            className="mt-1 rounded border border-border px-2 py-1 text-xs hover:bg-surface-hover"
          >
            New File
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
        onContextMenu={(event) => {
          event.preventDefault();
          openMenu(null, event.clientX, event.clientY, treeRef.current);
        }}
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
            onContextMenu={onRowContextMenu}
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
            {!project.readOnly && (
              <button
                type="button"
                onClick={() => setCreatingFile(true)}
                className="flex h-6 items-center gap-1 rounded px-1.5 text-[11px] text-fg-muted hover:bg-surface-hover hover:text-fg"
              >
                <FilePlus aria-hidden className="size-3.5" />
                New File
              </button>
            )}
            {fileOperations.enabled && (
              <IconButton label="New folder" onClick={() => newFolder(null)}>
                <FolderPlus aria-hidden className="size-4" />
              </IconButton>
            )}
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
      <CodeFileDialog
        open={creatingFile}
        onClose={() => setCreatingFile(false)}
        onCreate={actions.createCodeFile}
        onOpenExisting={(name) => void actions.openFile(name)}
      />
      <PathDialog request={dialog} onClose={() => setDialog(null)} />
      {menu && (
        <ContextMenu
          label={menu.node ? `Actions for ${menu.node.name}` : "Explorer actions"}
          x={menu.x}
          y={menu.y}
          items={menuItems(menu.node)}
          returnFocus={menu.returnFocus}
          onClose={() => setMenu(null)}
        />
      )}
      {content}
      <p role="status" aria-live="polite" className="sr-only">
        {notice}
      </p>
      {notice && (
        <p className="shrink-0 border-t border-border px-3 py-1.5 text-[11px] text-fg-muted">
          {notice}{" "}
          <button type="button" className="underline" onClick={() => setNotice(null)}>
            Dismiss
          </button>
        </p>
      )}
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
