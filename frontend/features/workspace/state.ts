import { ancestorPaths } from "@/lib/project-paths";
import type { LanguageId } from "@/lib/languages";
import type { AnalysisCapability, BackendLanguage } from "@/services/api/analysis";
import type { ProjectIntelligence } from "@/services/api/intelligence";
import type { Diagnostic } from "@/types/diagnostics";
import type { ProjectEntry, ProjectPath } from "@/types/project";

import type { ProjectSource } from "./sources/types";

export interface ProjectInfo {
  /** Unique per opened project instance; used to namespace editor models. */
  id: string;
  name: string;
  kind: ProjectSource["kind"];
  persistence: ProjectSource["persistence"];
  readOnly: boolean;
  /** Backend project id for server projects. */
  serverProjectId?: string;
  /** Folder linked on the server (server projects only). */
  rootPath?: string;
  skippedEntries: number;
  truncated: boolean;
}

/** Real-time analysis state of one file (diagnostics live in `diagnostics`). */
export type FileAnalysis =
  | { status: "pending" | "running" }
  | {
      status: "done";
      language: BackendLanguage;
      success: boolean;
      capabilities: AnalysisCapability[];
      errors: string[];
      durationMs: number;
    }
  /** The backend could not be reached; shown instead of stale results. */
  | { status: "unavailable"; message: string }
  | { status: "failed"; message: string };

export type IntelligenceState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "empty" }
  | { status: "ready"; data: ProjectIntelligence }
  | { status: "error"; message: string };

/** Producer key for backend analysis diagnostics. */
export const ANALYSIS_SOURCE = "analysis";

export type FileStatus = "loading" | "ready" | "error";

export interface FileBuffer {
  path: ProjectPath;
  status: FileStatus;
  /** Content as last loaded from / saved to the project source. */
  savedContent: string;
  /** Current editor content. */
  content: string;
  loadError?: string;
  saving: boolean;
  saveError?: string;
  languageOverride?: LanguageId;
}

export interface EditorSettings {
  fontSize: number;
  tabSize: number;
  wordWrap: boolean;
  minimap: boolean;
}

export const DEFAULT_EDITOR_SETTINGS: EditorSettings = {
  fontSize: 14,
  tabSize: 4,
  wordWrap: false,
  minimap: true,
};

export interface RevealRequest {
  path: ProjectPath;
  line: number;
  column: number;
  /** Changes on every request so repeated clicks on the same problem re-reveal. */
  nonce: number;
}

/** Replace a file's editor content (e.g. an applied AI fix); applied as one undoable edit. */
export interface ReplaceRequest {
  path: ProjectPath;
  content: string;
  nonce: number;
}

export interface WorkspaceState {
  projectStatus: "none" | "loading" | "ready" | "error";
  project: ProjectInfo | null;
  projectError?: string;
  entries: ProjectEntry[];
  buffers: Record<ProjectPath, FileBuffer>;
  openPaths: ProjectPath[];
  activePath: ProjectPath | null;
  /** Keyed by producer ("typescript", "ruff", ...) then by file path. */
  diagnostics: Record<string, Record<ProjectPath, Diagnostic[]>>;
  analysis: Record<ProjectPath, FileAnalysis>;
  intelligence: IntelligenceState;
  editorSettings: EditorSettings;
  reveal: RevealRequest | null;
  replace: ReplaceRequest | null;
}

export function createInitialState(
  editorSettings: EditorSettings = DEFAULT_EDITOR_SETTINGS,
): WorkspaceState {
  return {
    projectStatus: "none",
    project: null,
    entries: [],
    buffers: {},
    openPaths: [],
    activePath: null,
    diagnostics: {},
    analysis: {},
    intelligence: { status: "idle" },
    editorSettings,
    reveal: null,
    replace: null,
  };
}

export type WorkspaceAction =
  | { type: "project/loading" }
  | { type: "project/loaded"; project: ProjectInfo; entries: ProjectEntry[] }
  | { type: "project/failed"; error: string }
  | { type: "project/closed" }
  | { type: "project/entries-refreshed"; entries: ProjectEntry[] }
  | { type: "file/loading"; path: ProjectPath }
  | { type: "file/loaded"; path: ProjectPath; content: string }
  | { type: "file/load-failed"; path: ProjectPath; error: string }
  | { type: "file/created"; path: ProjectPath }
  | { type: "file/edited"; path: ProjectPath; content: string }
  | { type: "file/saving"; path: ProjectPath }
  | { type: "file/saved"; path: ProjectPath; content: string }
  | { type: "file/save-failed"; path: ProjectPath; error: string }
  | { type: "file/language-set"; path: ProjectPath; language: LanguageId | null }
  | { type: "tab/opened"; path: ProjectPath }
  | { type: "tab/activated"; path: ProjectPath }
  | { type: "tab/closed"; path: ProjectPath }
  | { type: "settings/changed"; settings: Partial<EditorSettings> }
  | { type: "diagnostics/replaced"; source: string; path: ProjectPath; diagnostics: Diagnostic[] }
  | { type: "editor/reveal"; request: RevealRequest }
  | { type: "editor/replace"; request: ReplaceRequest }
  | { type: "analysis/updated"; path: ProjectPath; analysis: FileAnalysis }
  | { type: "intelligence/updated"; intelligence: IntelligenceState };

export function isDirty(buffer: FileBuffer | undefined): boolean {
  return !!buffer && buffer.status === "ready" && buffer.content !== buffer.savedContent;
}

function updateBuffer(
  state: WorkspaceState,
  path: ProjectPath,
  update: (buffer: FileBuffer) => FileBuffer,
): WorkspaceState {
  const buffer = state.buffers[path];
  if (!buffer) return state;
  return { ...state, buffers: { ...state.buffers, [path]: update(buffer) } };
}

function readyBuffer(path: ProjectPath, content: string): FileBuffer {
  return { path, status: "ready", savedContent: content, content, saving: false };
}

export function workspaceReducer(state: WorkspaceState, action: WorkspaceAction): WorkspaceState {
  switch (action.type) {
    case "project/loading":
      return { ...createInitialState(state.editorSettings), projectStatus: "loading" };

    case "project/loaded":
      return {
        ...createInitialState(state.editorSettings),
        projectStatus: "ready",
        project: action.project,
        entries: action.entries,
      };

    case "project/failed":
      return {
        ...createInitialState(state.editorSettings),
        projectStatus: "error",
        projectError: action.error,
      };

    case "project/closed":
      return createInitialState(state.editorSettings);

    case "project/entries-refreshed":
      return { ...state, entries: action.entries };

    case "file/loading":
      return {
        ...state,
        buffers: {
          ...state.buffers,
          [action.path]: {
            path: action.path,
            status: "loading",
            savedContent: "",
            content: "",
            saving: false,
          },
        },
      };

    case "file/loaded":
      return updateBuffer(state, action.path, (buffer) => ({
        ...readyBuffer(action.path, action.content),
        languageOverride: buffer.languageOverride,
      }));

    case "file/load-failed":
      return updateBuffer(state, action.path, (buffer) => ({
        ...buffer,
        status: "error",
        loadError: action.error,
      }));

    case "file/created": {
      if (state.entries.some((entry) => entry.path === action.path)) return state;
      const known = new Set(state.entries.map((entry) => entry.path));
      const folders: ProjectEntry[] = ancestorPaths(action.path)
        .filter((path) => !known.has(path))
        .map((path) => ({ path, type: "folder" }));
      return {
        ...state,
        entries: [...state.entries, ...folders, { path: action.path, type: "file", size: 0 }],
        buffers: { ...state.buffers, [action.path]: readyBuffer(action.path, "") },
      };
    }

    case "file/edited":
      return updateBuffer(state, action.path, (buffer) =>
        buffer.status === "ready" && buffer.content !== action.content
          ? { ...buffer, content: action.content }
          : buffer,
      );

    case "file/saving":
      return updateBuffer(state, action.path, (buffer) => ({
        ...buffer,
        saving: true,
        saveError: undefined,
      }));

    case "file/saved":
      return updateBuffer(state, action.path, (buffer) => ({
        ...buffer,
        saving: false,
        savedContent: action.content,
      }));

    case "file/save-failed":
      return updateBuffer(state, action.path, (buffer) => ({
        ...buffer,
        saving: false,
        saveError: action.error,
      }));

    case "file/language-set":
      return updateBuffer(state, action.path, (buffer) => ({
        ...buffer,
        languageOverride: action.language ?? undefined,
      }));

    case "tab/opened":
      return {
        ...state,
        openPaths: state.openPaths.includes(action.path)
          ? state.openPaths
          : [...state.openPaths, action.path],
        activePath: action.path,
      };

    case "tab/activated":
      return state.openPaths.includes(action.path) ? { ...state, activePath: action.path } : state;

    case "tab/closed": {
      const index = state.openPaths.indexOf(action.path);
      if (index === -1) return state;
      const openPaths = state.openPaths.filter((path) => path !== action.path);
      const activePath =
        state.activePath === action.path
          ? (openPaths[Math.min(index, openPaths.length - 1)] ?? null)
          : state.activePath;
      // Closing discards unsaved edits (the UI confirms first); the buffer is
      // dropped so that reopening reloads from the project source.
      const { [action.path]: _closed, ...buffers } = state.buffers;
      const { [action.path]: _analysis, ...analysis } = state.analysis;
      // Problems are shown for open files only.
      const diagnostics = Object.fromEntries(
        Object.entries(state.diagnostics).map(([source, byFile]) => {
          const { [action.path]: _removed, ...rest } = byFile;
          return [source, rest];
        }),
      );
      return { ...state, openPaths, activePath, buffers, analysis, diagnostics };
    }

    case "settings/changed":
      return { ...state, editorSettings: { ...state.editorSettings, ...action.settings } };

    case "diagnostics/replaced": {
      const bySource = { ...(state.diagnostics[action.source] ?? {}) };
      if (action.diagnostics.length === 0) {
        if (!(action.path in bySource)) return state;
        delete bySource[action.path];
      } else {
        bySource[action.path] = action.diagnostics;
      }
      return { ...state, diagnostics: { ...state.diagnostics, [action.source]: bySource } };
    }

    case "editor/reveal":
      return { ...state, reveal: action.request };

    case "editor/replace": {
      const buffer = state.buffers[action.request.path];
      if (!buffer || buffer.status !== "ready") return state;
      return {
        ...state,
        buffers: {
          ...state.buffers,
          [action.request.path]: { ...buffer, content: action.request.content },
        },
        replace: action.request,
      };
    }

    case "analysis/updated":
      return { ...state, analysis: { ...state.analysis, [action.path]: action.analysis } };

    case "intelligence/updated":
      return { ...state, intelligence: action.intelligence };
  }
}
