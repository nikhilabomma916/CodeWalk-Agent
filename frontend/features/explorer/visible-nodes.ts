import type { ProjectFolderNode, ProjectTreeNode } from "@/types/project";

export interface VisibleNode {
  node: ProjectTreeNode;
  depth: number;
  parentPath: string | null;
}

/** Depth-first list of nodes currently visible given the expanded folders (root excluded). */
export function flattenVisible(
  root: ProjectFolderNode,
  expanded: ReadonlySet<string>,
): VisibleNode[] {
  const result: VisibleNode[] = [];
  const visit = (folder: ProjectFolderNode, depth: number) => {
    for (const child of folder.children) {
      result.push({ node: child, depth, parentPath: folder.path === "" ? null : folder.path });
      if (child.type === "folder" && expanded.has(child.path)) visit(child, depth + 1);
    }
  };
  visit(root, 0);
  return result;
}
