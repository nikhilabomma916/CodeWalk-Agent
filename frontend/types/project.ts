import type { LanguageId } from "@/lib/languages";

/** Paths are project-relative, "/"-separated, and double as stable node ids. */
export type ProjectPath = string;

export interface ProjectFileNode {
  type: "file";
  path: ProjectPath;
  name: string;
  language: LanguageId;
}

export interface ProjectFolderNode {
  type: "folder";
  path: ProjectPath;
  name: string;
  children: ProjectTreeNode[];
}

export type ProjectTreeNode = ProjectFileNode | ProjectFolderNode;

/** A flat listing entry as produced by a project source (local folder, backend, ...). */
export interface ProjectEntry {
  path: ProjectPath;
  type: "file" | "folder";
  size?: number;
}
