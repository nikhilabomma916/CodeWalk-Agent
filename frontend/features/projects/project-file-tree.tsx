"use client";

import { ChevronDown, ChevronRight } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { FileIcon, FolderIcon } from "@/features/explorer/file-icon";
import { KIND_LABEL } from "@/features/intelligence/intelligence-panel";
import { codingHref } from "@/features/workspace/use-coding-deep-link";
import { backendLanguageLabel } from "@/lib/format";
import { ancestorPaths, buildTree } from "@/lib/project-paths";
import type { ProjectIntelligence } from "@/services/api/intelligence";
import type { ServerFile } from "@/services/api/projects";
import type { ProjectEntry, ProjectFolderNode, ProjectTreeNode } from "@/types/project";

type IntelligenceFile = ProjectIntelligence["files"][number];

interface TreeProps {
  projectId: string;
  projectName: string;
  files: ServerFile[];
  /** Latest project intelligence, when the project has been analyzed. */
  intelligence: ProjectIntelligence | null;
}

const INDENT = 12;

/**
 * Read-only explorer of a stored project. Clicking a file opens it in the
 * Coding area; files with known symbols expand to list them (each opens the
 * file at the symbol's line).
 */
export function ProjectFileTree({ projectId, projectName, files, intelligence }: TreeProps) {
  const tree = useMemo(() => {
    const folders = new Set<string>();
    files.forEach((file) => ancestorPaths(file.path).forEach((folder) => folders.add(folder)));
    const entries: ProjectEntry[] = [
      ...[...folders].map((path) => ({ path, type: "folder" as const })),
      ...files.map((file) => ({ path: file.path, type: "file" as const })),
    ];
    return buildTree(entries, projectName);
  }, [files, projectName]);
  const byPath = useMemo(() => new Map(files.map((file) => [file.path, file])), [files]);
  const structure = useMemo(
    () => new Map((intelligence?.files ?? []).map((file) => [file.path, file])),
    [intelligence],
  );
  // Top-level folders start open; deeper ones on demand.
  const [expanded, setExpanded] = useState<Set<string>>(
    () =>
      new Set(
        tree.children.filter((node) => node.type === "folder").map((node) => `folder:${node.path}`),
      ),
  );

  const toggle = (path: string) =>
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });

  if (files.length === 0) {
    return <p className="px-3 py-4 text-xs text-fg-muted">This project has no files yet.</p>;
  }

  const renderNode = (node: ProjectTreeNode, depth: number) => {
    const key = `${node.type}:${node.path}`;
    const open = expanded.has(key);
    if (node.type === "folder") {
      return (
        <li key={key} role="treeitem" aria-expanded={open} aria-selected={false}>
          <button
            type="button"
            onClick={() => toggle(key)}
            className="flex h-6 w-full items-center gap-1 pr-2 text-left text-xs text-fg hover:bg-surface-hover"
            style={{ paddingLeft: depth * INDENT + 4 }}
          >
            {open ? (
              <ChevronDown aria-hidden className="size-3.5 shrink-0 text-fg-subtle" />
            ) : (
              <ChevronRight aria-hidden className="size-3.5 shrink-0 text-fg-subtle" />
            )}
            <FolderIcon open={open} />
            <span className="truncate">{node.name}</span>
          </button>
          {open && <ul role="group">{renderChildren(node, depth + 1)}</ul>}
        </li>
      );
    }

    const file = byPath.get(node.path);
    const info: IntelligenceFile | undefined = structure.get(node.path);
    const symbols = info?.symbols ?? [];
    return (
      <li
        key={key}
        role="treeitem"
        aria-selected={false}
        aria-expanded={symbols.length ? open : undefined}
      >
        <div
          className="group flex h-6 items-center gap-1 pr-2 text-xs hover:bg-surface-hover"
          style={{ paddingLeft: depth * INDENT + 4 }}
        >
          {symbols.length > 0 ? (
            <button
              type="button"
              onClick={() => toggle(key)}
              aria-label={`${open ? "Hide" : "Show"} symbols in ${node.name}`}
              className="text-fg-subtle hover:text-fg"
            >
              {open ? (
                <ChevronDown aria-hidden className="size-3.5" />
              ) : (
                <ChevronRight aria-hidden className="size-3.5" />
              )}
            </button>
          ) : (
            <span aria-hidden className="w-3.5 shrink-0" />
          )}
          <FileIcon language={node.language} />
          <Link
            href={codingHref(projectId, node.path)}
            className="min-w-0 flex-1 truncate text-fg hover:underline"
            title={`Open ${node.path} in Coding`}
          >
            {node.name}
          </Link>
          {file && (
            <span className="shrink-0 text-[10px] text-fg-subtle">
              {backendLanguageLabel(file.language)}
            </span>
          )}
          {symbols.length > 0 && (
            <span className="w-14 shrink-0 text-right text-[10px] text-fg-subtle">
              {symbols.length} sym
            </span>
          )}
        </div>
        {open && symbols.length > 0 && (
          <ul role="group">
            {symbols.map((symbol) => (
              <li key={symbol.id} role="treeitem" aria-selected={false}>
                <Link
                  href={codingHref(projectId, node.path, symbol.line)}
                  className="flex h-5 items-center gap-1.5 pr-2 text-[11px] hover:bg-surface-hover"
                  style={{ paddingLeft: (depth + 1) * INDENT + 22 }}
                  title={symbol.signature ?? symbol.qualified_name}
                >
                  <span className="w-12 shrink-0 text-fg-subtle">{KIND_LABEL[symbol.kind]}</span>
                  <span className="truncate font-mono text-fg">{symbol.qualified_name}</span>
                  <span className="ml-auto shrink-0 text-fg-subtle">:{symbol.line}</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </li>
    );
  };

  const renderChildren = (folder: ProjectFolderNode, depth: number) =>
    folder.children.map((child) => renderNode(child, depth));

  return (
    <ul role="tree" aria-label={`Files of ${projectName}`} className="py-1">
      {renderChildren(tree, 0)}
    </ul>
  );
}
