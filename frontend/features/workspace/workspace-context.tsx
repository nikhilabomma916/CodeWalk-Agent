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
import { getProject, type ServerProject } from "@/services/api/projects";
import type { Diagnostic } from "@/types/diagnostics";
import type { ProjectFolderNode, ProjectPath } from "@/types/project";

import { LocalDirectorySource, supportsDirectoryAccess } from "./sources/local-directory-source";
import { LocalSnapshotSource } from "./sources/local-snapshot-source";
import { MemoryProjectSource } from "./sources/memory-source";
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
  setLanguage(path: ProjectPath, language: LanguageId | null): void;
  updateSettings(settings: Partial<EditorSettings>): void;
  replaceDiagnostics(source: string, path: ProjectPath, diagnostics: Diagnostic[]): void;
  setAnalysis(path: ProjectPath, analysis: FileAnalysis): void;
  revealPosition(path: ProjectPath, line: number, column: number): Promise<void>;
  /** Opens a project stored by the backend. Resolves false if the user kept the current one. */
  openServerProject(project: ServerProject): Promise<boolean>;
  /** Reopens the server project used last (after a page reload); false if none/unavailable. */
  restoreServerProject(): Promise<boolean>;
  /** Runs project intelligence (rescanning linked folders) and refreshes the file tree. */
  analyzeServerProject(): Promise<void>;
  /** Loads the latest stored project intelligence, if any. */
  loadIntelligence(): Promise<void>;
}

interface WorkspaceContextValue {
  state: WorkspaceState;
  tree: ProjectFolderNode | null;
  actions: WorkspaceActions;
  canOpenDirectory: boolean;
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

      async openServerProject(project) {
        if (!(await confirmDiscardAll())) return false;
        await loadSource(new ServerProjectSource(project));
        return true;
      },

      async restoreServerProject() {
        const id = lastServerProject();
        if (!id || sourceRef.current) return false;
        try {
          const project = await getProject(id);
          if (sourceRef.current) return false;
          await loadSource(new ServerProjectSource(project));
          return true;
        } catch (error) {
          if (isApiError(error) && error.status === 404) rememberServerProject(null);
          return false;
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
    }),
    [confirm, confirmDiscardAll, loadIntelligence, loadSource, openFile, saveFile],
  );

  const tree = useMemo(
    () => (state.project ? buildTree(state.entries, state.project.name) : null),
    [state.entries, state.project],
  );

  const value = useMemo(
    () => ({ state, tree, actions, canOpenDirectory }),
    [state, tree, actions, canOpenDirectory],
  );

  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}

export function useWorkspace(): WorkspaceContextValue {
  const value = useContext(WorkspaceContext);
  if (!value) throw new Error("useWorkspace must be used inside <WorkspaceProvider>");
  return value;
}
