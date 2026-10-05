"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  useSyncExternalStore,
  type ReactNode,
} from "react";

import { useConfirm } from "@/components/ui/confirm-dialog";
import { buildTree } from "@/lib/project-paths";
import type { LanguageId } from "@/lib/languages";
import { isApiError } from "@/services/api/errors";
import { analyzeProject, getProjectIntelligence } from "@/services/api/intelligence";
import {
  createProject as createServerProject,
  getProject,
  type ServerProject,
} from "@/services/api/projects";
import type { Diagnostic } from "@/types/diagnostics";
import type { ProjectFolderNode, ProjectPath } from "@/types/project";

import { LocalDirectorySource, supportsDirectoryAccess } from "./sources/local-directory-source";
import { LocalSnapshotSource } from "./sources/local-snapshot-source";
import { MemoryProjectSource } from "./sources/memory-source";
import { uploadTextFiles, type UploadOutcome, type UploadProgress } from "./folder-upload";
import { ServerProjectSource } from "./sources/server-source";
import { SourceError, type ProjectSource } from "./sources/types";
import {
  createInitialState,
  DEFAULT_EDITOR_SETTINGS,
  isDirty,
  workspaceReducer,
  type EditorSettings,
  type FileAnalysis,
  type WorkspaceState,
} from "./state";

const SETTINGS_STORAGE_KEY = "codewalk.editorSettings";
const LAST_SERVER_PROJECT_KEY = "codewalk.lastServerProject";

function rememberServerProject(id: string | null): void {
  try {
    if (id) window.localStorage.setItem(LAST_SERVER_PROJECT_KEY, id);
    else window.localStorage.removeItem(LAST_SERVER_PROJECT_KEY);
  } catch {
    // Storage unavailable: the project is simply not reopened automatically.
  }
}

function lastServerProject(): string | null {
  try {
    return window.localStorage.getItem(LAST_SERVER_PROJECT_KEY);
  } catch {
    return null;
  }
}

function loadStoredSettings(): EditorSettings {
  try {
    const raw = window.localStorage.getItem(SETTINGS_STORAGE_KEY);
    if (!raw) return DEFAULT_EDITOR_SETTINGS;
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== "object" || parsed === null) return DEFAULT_EDITOR_SETTINGS;
    const stored = parsed as Partial<Record<keyof EditorSettings, unknown>>;
    return {
      fontSize:
        typeof stored.fontSize === "number" ? stored.fontSize : DEFAULT_EDITOR_SETTINGS.fontSize,
      tabSize:
        typeof stored.tabSize === "number" ? stored.tabSize : DEFAULT_EDITOR_SETTINGS.tabSize,
      wordWrap:
        typeof stored.wordWrap === "boolean" ? stored.wordWrap : DEFAULT_EDITOR_SETTINGS.wordWrap,
      minimap:
        typeof stored.minimap === "boolean" ? stored.minimap : DEFAULT_EDITOR_SETTINGS.minimap,
    };
  } catch {
    return DEFAULT_EDITOR_SETTINGS;
  }
}

function errorMessage(error: unknown, fallback: string): string {
  if (error instanceof SourceError) return error.message;
  if (isApiError(error)) return error.message;
  return fallback;
}

let projectCounter = 0;

export interface FileOperations {
  /** New file, new folder, rename, move, delete, duplicate. */
  enabled: boolean;
  /** Shown when they are not available. */
  reason: string | null;
}

/** File operations by project kind: server and in-browser projects support them all. */
export function fileOperationsFor(
  project: { kind: string; readOnly: boolean } | null,
): FileOperations {
  if (!project) return { enabled: false, reason: "Open a project first." };
  if (project.readOnly)
    return { enabled: false, reason: "This project is read-only (linked to a server folder)." };
  if (project.kind === "server" || project.kind === "memory")
    return { enabled: true, reason: null };
  if (project.kind === "local-snapshot")
    return {
      enabled: false,
      reason: "A folder opened as a copy is read-only. Save it to CodeWalk to edit it.",
    };
  return {
    enabled: false,
    reason:
      "Renaming and deleting files of a local folder is not supported here. Save it to CodeWalk to manage its files.",
  };
}

/** "name copy.ext", then "name copy 2.ext", ... that does not exist yet. */
export function duplicatePath(
  path: ProjectPath,
  exists: (path: ProjectPath) => boolean,
): ProjectPath {
  const slash = path.lastIndexOf("/");
  const folder = slash >= 0 ? path.slice(0, slash + 1) : "";
  const name = path.slice(slash + 1);
  const dot = name.lastIndexOf(".");
  const [stem, ext] = dot > 0 ? [name.slice(0, dot), name.slice(dot)] : [name, ""];
  for (let n = 1; ; n++) {
    const candidate = `${folder}${stem} copy${n === 1 ? "" : ` ${n}`}${ext}`;
    if (!exists(candidate)) return candidate;
  }
}

/** Browser capabilities never change during a session. */
const subscribeNever = () => () => {};

export interface WorkspaceActions {
  createProject(name: string): Promise<void>;
  /** Opens a folder with read/write access (Chromium File System Access API). */
  openDirectory(): Promise<void>;
  /** Opens a folder picked with <input webkitdirectory> (read-only copy). */
  openSnapshot(files: FileList): Promise<void>;
  /** Closes the project, asking about unsaved changes. Resolves false if the user cancelled. */
  closeProject(): Promise<boolean>;
  openFile(path: ProjectPath): Promise<void>;
  activateTab(path: ProjectPath): void;
  /** Closes a tab, asking what to do with unsaved changes. Resolves false if cancelled. */
  closeTab(path: ProjectPath): Promise<boolean>;
  editFile(path: ProjectPath, content: string): void;
  saveFile(path: ProjectPath): Promise<boolean>;
  createFile(path: ProjectPath): Promise<void>;
  /**
   * Coding "+ New File": creates a code file from a file name only (at the project root) and opens it.
   * Rejects with a SourceError ("exists", "invalid", "read-only", ...) for the dialog to show.
   */
  createCodeFile(name: string): Promise<void>;
  /** Creates an (empty) folder. Folders are stored through a .gitkeep file inside them. */
  createFolder(path: ProjectPath): Promise<void>;
  /** Renames/moves a file or a folder (with everything in it); open files follow, edits kept. */
  renamePath(from: ProjectPath, to: ProjectPath): Promise<void>;
  /**
   * Deletes a file or a folder after asking for confirmation. Resolves false if cancelled.
   * Unsaved edits in deleted files are discarded (the confirmation says so).
   */
  deletePath(path: ProjectPath): Promise<boolean>;
  /** Copies a file (its current editor content) to "<name> copy.<ext>" and opens the copy. */
  duplicateFile(path: ProjectPath): Promise<ProjectPath>;
  setLanguage(path: ProjectPath, language: LanguageId | null): void;
  updateSettings(settings: Partial<EditorSettings>): void;
  replaceDiagnostics(source: string, path: ProjectPath, diagnostics: Diagnostic[]): void;
  setAnalysis(path: ProjectPath, analysis: FileAnalysis): void;
  revealPosition(path: ProjectPath, line: number, column: number): Promise<void>;
  /**
   * Replaces an open file's content in the editor (one undoable edit; the file is then unsaved).
   * Used when the developer applies a reviewed AI fix.
   */
  replaceContent(path: ProjectPath, content: string): void;
  /**
   * The backend saved new content for a file (an approved agent change). An open buffer shows it as
   * one undoable edit and is marked saved; files that are not open load it when opened.
   */
  syncSavedContent(path: ProjectPath, content: string): void;
  /**
   * Saves a browser-only project (in memory or a local folder) as a CodeWalk project on the server,
   * including unsaved editor content, then opens it from the server. Server features (agent,
   * history, project search, insights) need this. Files the server refuses (credentials, binary,
   * too large) are reported, never silently dropped.
   */
  saveToServer(options?: {
    onProgress?(progress: UploadProgress): void;
  }): Promise<UploadOutcome & { project: ServerProject }>;
  /** Opens a project stored by the backend. Resolves false if the user kept the current one. */
  openServerProject(project: ServerProject): Promise<boolean>;
  /** Reopens the server project used last (after a page reload); false if none/unavailable. */
  restoreServerProject(): Promise<boolean>;
  /** Runs project intelligence (rescanning linked folders) and refreshes the file tree. */
  analyzeServerProject(): Promise<void>;
  /** Loads the latest stored project intelligence, if any. */
  loadIntelligence(): Promise<void>;
  /** Re-reads the file list (e.g. after an approved proposal created a file). */
  refreshEntries(): Promise<void>;
}

interface WorkspaceContextValue {
  state: WorkspaceState;
  tree: ProjectFolderNode | null;
  actions: WorkspaceActions;
  canOpenDirectory: boolean;
  /** Which Explorer operations the open project supports (and why not, when it does not). */
  fileOperations: FileOperations;
}

const WorkspaceContext = createContext<WorkspaceContextValue | null>(null);

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  // Stored settings only affect client-rendered UI (Monaco, the settings menu),
  // so reading them in the initializer cannot cause a hydration mismatch.
  const [state, dispatch] = useReducer(workspaceReducer, undefined, () =>
    createInitialState(
      typeof window === "undefined" ? DEFAULT_EDITOR_SETTINGS : loadStoredSettings(),
    ),
  );
  const confirm = useConfirm();
  const sourceRef = useRef<ProjectSource | null>(null);
  const stateRef = useRef(state);
  const canOpenDirectory = useSyncExternalStore(
    subscribeNever,
    supportsDirectoryAccess,
    () => false,
  );
  const revealNonce = useRef(0);

  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  useEffect(() => {
    try {
      window.localStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify(state.editorSettings));
    } catch {
      // Storage may be unavailable (private mode); settings then last for this session only.
    }
  }, [state.editorSettings]);

  // Warn before leaving the page with unsaved edits.
  const hasUnsaved = Object.values(state.buffers).some(isDirty);
  useEffect(() => {
    if (!hasUnsaved) return;
    const handler = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [hasUnsaved]);

  const confirmDiscardAll = useCallback(async (): Promise<boolean> => {
    const dirty = Object.values(stateRef.current.buffers).filter(isDirty);
    if (dirty.length === 0) return true;
    const choice = await confirm({
      title: "Discard unsaved changes?",
      message: `${dirty.length} file${dirty.length === 1 ? " has" : "s have"} unsaved changes that will be lost.`,
      actions: [
        { value: "cancel", label: "Cancel" },
        { value: "discard", label: "Discard changes", variant: "danger" },
      ],
      cancelValue: "cancel",
    });
    return choice === "discard";
  }, [confirm]);

  const loadSource = useCallback(async (source: ProjectSource) => {
    sourceRef.current = source;
    dispatch({ type: "project/loading" });
    try {
      const listing = await source.list();
      if (sourceRef.current !== source) return;
      projectCounter += 1;
      dispatch({
        type: "project/loaded",
        project: {
          id: `p${projectCounter}`,
          name: source.name,
          kind: source.kind,
          persistence: source.persistence,
          readOnly: source.readOnly,
          serverProjectId: source.serverProjectId,
          rootPath: source instanceof ServerProjectSource ? source.rootPath : undefined,
          skippedEntries: listing.skipped,
          truncated: listing.truncated,
        },
        entries: listing.entries,
      });
    } catch (error) {
      if (sourceRef.current !== source) return;
      sourceRef.current = null;
      dispatch({ type: "project/failed", error: errorMessage(error, "Unable to load project.") });
      return;
    }
    rememberServerProject(source.serverProjectId ?? null);
  }, []);

  const loadIntelligence = useCallback(async () => {
    const source = sourceRef.current;
    if (!source?.serverProjectId) return;
    dispatch({ type: "intelligence/updated", intelligence: { status: "loading" } });
    try {
      const data = await getProjectIntelligence(source.serverProjectId);
      if (sourceRef.current !== source) return;
      dispatch({
        type: "intelligence/updated",
        intelligence: data ? { status: "ready", data } : { status: "empty" },
      });
    } catch (error) {
      if (sourceRef.current !== source) return;
      dispatch({
        type: "intelligence/updated",
        intelligence: {
          status: "error",
          message: errorMessage(error, "Unable to load project intelligence."),
        },
      });
    }
  }, []);

  const openFile = useCallback(async (path: ProjectPath) => {
    const source = sourceRef.current;
    if (!source) return;
    const existing = stateRef.current.buffers[path];
    dispatch({ type: "tab/opened", path });
    if (existing && existing.status !== "error") return;

    dispatch({ type: "file/loading", path });
    try {
      const content = await source.read(path);
      if (sourceRef.current === source) dispatch({ type: "file/loaded", path, content });
    } catch (error) {
      if (sourceRef.current === source) {
        dispatch({
          type: "file/load-failed",
          path,
          error: errorMessage(error, `Unable to open ${path}.`),
        });
      }
    }
  }, []);

  const saveFile = useCallback(async (path: ProjectPath): Promise<boolean> => {
    const source = sourceRef.current;
    const buffer = stateRef.current.buffers[path];
    if (!source || !buffer || buffer.status !== "ready" || buffer.saving) return false;
    const content = buffer.content;
    dispatch({ type: "file/saving", path });
    try {
      await source.write(path, content);
      if (sourceRef.current !== source) return false;
      dispatch({ type: "file/saved", path, content });
      return true;
    } catch (error) {
      if (sourceRef.current === source) {
        dispatch({
          type: "file/save-failed",
          path,
          error: errorMessage(error, `Unable to save ${path}.`),
        });
      }
      return false;
    }
  }, []);

  const actions = useMemo<WorkspaceActions>(
    () => ({
      async createProject(name) {
        if (!(await confirmDiscardAll())) return;
        await loadSource(new MemoryProjectSource(name));
      },

      async openDirectory() {
        if (!window.showDirectoryPicker) return;
        let handle: FileSystemDirectoryHandle;
        try {
          handle = await window.showDirectoryPicker({ id: "codewalk-project", mode: "readwrite" });
        } catch (error) {
          if (error instanceof DOMException && error.name === "AbortError") return; // picker dismissed
          dispatch({
            type: "project/failed",
            error: "The folder could not be opened. Permission may have been denied.",
          });
          return;
        }
        if (!(await confirmDiscardAll())) return;
        await loadSource(new LocalDirectorySource(handle));
      },

      async openSnapshot(files) {
        if (files.length === 0) return;
        if (!(await confirmDiscardAll())) return;
        await loadSource(
          new LocalSnapshotSource(LocalSnapshotSource.folderName(files), Array.from(files)),
        );
      },

      async closeProject() {
        if (!(await confirmDiscardAll())) return false;
        sourceRef.current = null;
        rememberServerProject(null);
        dispatch({ type: "project/closed" });
        return true;
      },

      async saveToServer(options = {}) {
        const source = sourceRef.current;
        if (!source) throw new SourceError("invalid", "Open a project first.");
        if (source.serverProjectId)
          throw new SourceError("invalid", "This project is already saved on the server.");
        const files = stateRef.current.entries.filter((entry) => entry.type === "file");
        const project = await createServerProject({ name: source.name });
        const outcome = await uploadTextFiles(
          project.id,
          files.map(({ path }) => ({
            path,
            // The editor's content wins (it may have unsaved edits); otherwise read the source.
            read: async () => {
              const buffer = stateRef.current.buffers[path];
              return buffer?.status === "ready" ? buffer.content : source.read(path);
            },
          })),
          { onProgress: options.onProgress },
        );
        // Everything was uploaded with its current content, so nothing unsaved is lost here.
        if (sourceRef.current === source) await loadSource(new ServerProjectSource(project));
        return { ...outcome, project };
      },

      async openServerProject(project) {
        // Uploaded folders are analyzed in the Uploads area, never edited in Coding.
        if (project.origin === "upload") return false;
        if (!(await confirmDiscardAll())) return false;
        await loadSource(new ServerProjectSource(project));
        return true;
      },

      async restoreServerProject() {
        const id = lastServerProject();
        if (!id || sourceRef.current) return false;
        try {
          const project = await getProject(id);
          if (sourceRef.current || project.origin === "upload") return false;
          await loadSource(new ServerProjectSource(project));
          return true;
        } catch (error) {
          if (isApiError(error) && error.status === 404) rememberServerProject(null);
          return false;
        }
      },

      async refreshEntries() {
        const source = sourceRef.current;
        if (!source) return;
        const listing = await source.list();
        if (sourceRef.current === source) {
          dispatch({ type: "project/entries-refreshed", entries: listing.entries });
        }
      },

      async analyzeServerProject() {
        const source = sourceRef.current;
        if (!source?.serverProjectId) return;
        dispatch({ type: "intelligence/updated", intelligence: { status: "loading" } });
        try {
          const data = await analyzeProject(source.serverProjectId);
          if (sourceRef.current !== source) return;
          dispatch({ type: "intelligence/updated", intelligence: { status: "ready", data } });
          // A rescan of a linked folder can add or remove files.
          const listing = await source.list();
          if (sourceRef.current === source) {
            dispatch({ type: "project/entries-refreshed", entries: listing.entries });
          }
        } catch (error) {
          if (sourceRef.current !== source) return;
          dispatch({
            type: "intelligence/updated",
            intelligence: {
              status: "error",
              message: errorMessage(error, "Project analysis failed."),
            },
          });
        }
      },

      loadIntelligence,

      openFile,

      activateTab(path) {
        dispatch({ type: "tab/activated", path });
      },

      async closeTab(path) {
        const buffer = stateRef.current.buffers[path];
        if (isDirty(buffer)) {
          const choice = await confirm({
            title: "Save changes before closing?",
            message: (
              <>
                <span className="font-mono text-fg">{path}</span> has unsaved changes.
              </>
            ),
            actions: [
              { value: "save", label: "Save", variant: "primary" },
              { value: "discard", label: "Don't save", variant: "danger" },
              { value: "cancel", label: "Cancel" },
            ],
            cancelValue: "cancel",
          });
          if (choice === "cancel") return false;
          if (choice === "save" && !(await saveFile(path))) return false;
        }
        dispatch({ type: "tab/closed", path });
        return true;
      },

      editFile(path, content) {
        dispatch({ type: "file/edited", path, content });
      },

      saveFile,

      async createFile(path) {
        const source = sourceRef.current;
        if (!source) return;
        await source.createFile(path); // SourceError propagates to the caller's form
        if (sourceRef.current !== source) return;
        dispatch({ type: "file/created", path });
        dispatch({ type: "tab/opened", path });
      },

      async createCodeFile(name) {
        const source = sourceRef.current;
        if (!source) return;
        const fileName = name.trim();
        if (source.createCodeFile) await source.createCodeFile(fileName);
        else await source.createFile(fileName);
        if (sourceRef.current !== source) return;
        dispatch({ type: "file/created", path: fileName });
        dispatch({ type: "tab/opened", path: fileName });
      },

      async createFolder(path) {
        const source = sourceRef.current;
        if (!source) return;
        const keep = `${path.replace(/\/+$/, "")}/.gitkeep`;
        if (source.createFileWithContent) await source.createFileWithContent(keep, "");
        else await source.createFile(keep);
        if (sourceRef.current !== source) return;
        dispatch({ type: "file/created", path: keep });
      },

      async renamePath(from, to) {
        const source = sourceRef.current;
        if (!source?.renamePath)
          throw new SourceError(
            "read-only",
            fileOperationsFor(stateRef.current.project).reason ?? "Renaming is not supported here.",
          );
        if (from === to) return;
        await source.renamePath(from, to); // SourceError ("exists", "invalid", ...) for the dialog
        if (sourceRef.current !== source) return;
        dispatch({ type: "paths/renamed", from, to });
      },

      async deletePath(path) {
        const source = sourceRef.current;
        if (!source?.deletePath)
          throw new SourceError(
            "read-only",
            fileOperationsFor(stateRef.current.project).reason ?? "Deleting is not supported here.",
          );
        const current = stateRef.current;
        const files = current.entries.filter(
          (entry) =>
            entry.type === "file" && (entry.path === path || entry.path.startsWith(`${path}/`)),
        );
        const unsaved = files.filter((entry) => isDirty(current.buffers[entry.path])).length;
        const isFolder = !files.some((entry) => entry.path === path);
        const choice = await confirm({
          title: isFolder ? `Delete folder ${path}?` : `Delete ${path}?`,
          message:
            (isFolder
              ? `${files.length} file${files.length === 1 ? "" : "s"} will be deleted. `
              : "") +
            (source.persistence === "server"
              ? "The file history (saved versions) of deleted files is removed as well; the deletion is recorded in History."
              : "This cannot be undone.") +
            (unsaved
              ? ` ${unsaved} file${unsaved === 1 ? " has" : "s have"} unsaved changes that will be lost.`
              : ""),
          actions: [
            { value: "cancel", label: "Cancel" },
            { value: "delete", label: "Delete", variant: "danger" },
          ],
          cancelValue: "cancel",
        });
        if (choice !== "delete") return false;
        await source.deletePath(path);
        if (sourceRef.current !== source) return true;
        dispatch({ type: "paths/removed", path });
        return true;
      },

      async duplicateFile(path) {
        const source = sourceRef.current;
        if (!source?.createFileWithContent)
          throw new SourceError(
            "read-only",
            fileOperationsFor(stateRef.current.project).reason ??
              "Duplicating is not supported here.",
          );
        const current = stateRef.current;
        const buffer = current.buffers[path];
        const content = buffer?.status === "ready" ? buffer.content : await source.read(path);
        const known = new Set(current.entries.map((entry) => entry.path));
        const target = duplicatePath(path, (candidate) => known.has(candidate));
        await source.createFileWithContent(target, content);
        if (sourceRef.current !== source) return target;
        dispatch({ type: "file/created", path: target });
        dispatch({ type: "file/loaded", path: target, content });
        dispatch({ type: "tab/opened", path: target });
        return target;
      },

      setLanguage(path, language) {
        dispatch({ type: "file/language-set", path, language });
      },

      updateSettings(settings) {
        dispatch({ type: "settings/changed", settings });
      },

      replaceDiagnostics(source, path, diagnostics) {
        dispatch({ type: "diagnostics/replaced", source, path, diagnostics });
      },

      setAnalysis(path, analysis) {
        dispatch({ type: "analysis/updated", path, analysis });
      },

      async revealPosition(path, line, column) {
        await openFile(path);
        revealNonce.current += 1;
        dispatch({
          type: "editor/reveal",
          request: { path, line, column, nonce: revealNonce.current },
        });
      },

      syncSavedContent(path, content) {
        revealNonce.current += 1;
        dispatch({ type: "editor/synced", request: { path, content, nonce: revealNonce.current } });
      },

      replaceContent(path, content) {
        revealNonce.current += 1;
        dispatch({
          type: "editor/replace",
          request: { path, content, nonce: revealNonce.current },
        });
      },
    }),
    [confirm, confirmDiscardAll, loadIntelligence, loadSource, openFile, saveFile],
  );

  const tree = useMemo(
    () => (state.project ? buildTree(state.entries, state.project.name) : null),
    [state.entries, state.project],
  );

  const value = useMemo(
    () => ({
      state,
      tree,
      actions,
      canOpenDirectory,
      fileOperations: fileOperationsFor(state.project),
    }),
    [state, tree, actions, canOpenDirectory],
  );

  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}

export function useWorkspace(): WorkspaceContextValue {
  const value = useContext(WorkspaceContext);
  if (!value) throw new Error("useWorkspace must be used inside <WorkspaceProvider>");
  return value;
}
