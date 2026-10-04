import { detectLanguage } from "@/lib/languages";
import type {
  ProjectEntry,
  ProjectFolderNode,
  ProjectPath,
  ProjectTreeNode,
} from "@/types/project";

/** Generated/dependency directories that are never loaded into the workspace. */
export const IGNORED_DIRECTORIES: ReadonlySet<string> = new Set([
  ".git",
  "node_modules",
  "__pycache__",
  ".venv",
  "venv",
  "dist",
  "build",
  "coverage",
  ".idea",
  ".vscode",
  ".next",
  ".mypy_cache",
  ".pytest_cache",
  ".ruff_cache",
]);

const IGNORED_FILES: ReadonlySet<string> = new Set([".DS_Store", "Thumbs.db"]);

/** Secrets files are skipped so they are never read into the browser workspace. */
export function isSecretFile(name: string): boolean {
  return name === ".env" || (name.startsWith(".env.") && name !== ".env.example");
}

export function isIgnoredName(name: string, type: "file" | "folder"): boolean {
  if (type === "folder") return IGNORED_DIRECTORIES.has(name);
  return IGNORED_FILES.has(name) || isSecretFile(name);
}

/** True when any segment of the path is ignored (used for flat listings such as webkitdirectory). */
export function isIgnoredPath(path: ProjectPath): boolean {
  const segments = path.split("/");
  const fileName = segments.pop() ?? "";
  return (
    segments.some((segment) => IGNORED_DIRECTORIES.has(segment)) || isIgnoredName(fileName, "file")
  );
}

export function basename(path: ProjectPath): string {
  return path.slice(path.lastIndexOf("/") + 1);
}

export function dirname(path: ProjectPath): ProjectPath {
  const index = path.lastIndexOf("/");
  return index === -1 ? "" : path.slice(0, index);
}

export function joinPath(parent: ProjectPath, name: string): ProjectPath {
  return parent ? `${parent}/${name}` : name;
}

/** All ancestor folder paths, outermost first: "a/b/c.ts" -> ["a", "a/b"]. */
export function ancestorPaths(path: ProjectPath): ProjectPath[] {
  const segments = path.split("/").slice(0, -1);
  return segments.map((_, index) => segments.slice(0, index + 1).join("/"));
}

function compareNodes(a: ProjectTreeNode, b: ProjectTreeNode): number {
  if (a.type !== b.type) return a.type === "folder" ? -1 : 1;
  return a.name.localeCompare(b.name, undefined, { sensitivity: "base", numeric: true });
}

/** Builds a sorted tree (folders first) from a flat entry list; missing parent folders are implied. */
export function buildTree(entries: Iterable<ProjectEntry>, rootName: string): ProjectFolderNode {
  const root: ProjectFolderNode = { type: "folder", path: "", name: rootName, children: [] };
  const folders = new Map<ProjectPath, ProjectFolderNode>([["", root]]);

  const ensureFolder = (path: ProjectPath): ProjectFolderNode => {
    const existing = folders.get(path);
    if (existing) return existing;
    const folder: ProjectFolderNode = { type: "folder", path, name: basename(path), children: [] };
    folders.set(path, folder);
    ensureFolder(dirname(path)).children.push(folder);
    return folder;
  };

  for (const entry of entries) {
    if (entry.type === "folder") {
      ensureFolder(entry.path);
    } else {
      ensureFolder(dirname(entry.path)).children.push({
        type: "file",
        path: entry.path,
        name: basename(entry.path),
        language: detectLanguage(entry.path),
      });
    }
  }

  const sortRecursively = (folder: ProjectFolderNode) => {
    folder.children.sort(compareNodes);
    folder.children.forEach((child) => child.type === "folder" && sortRecursively(child));
  };
  sortRecursively(root);
  return root;
}
