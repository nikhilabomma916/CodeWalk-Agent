"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Group, Panel, Separator, usePanelRef } from "react-resizable-panels";

import { ConfirmProvider } from "@/components/ui/confirm-dialog";
import { useBackendHealth } from "@/features/backend-status/use-backend-health";
import { CursorProvider } from "@/features/editor/cursor-context";
import { EditorArea } from "@/features/editor/editor-area";
import { ProjectExplorer } from "@/features/explorer/project-explorer";
import { ProblemsPanel } from "@/features/problems/problems-panel";
import { StatusBar } from "@/features/status-bar/status-bar";

import { AppHeader } from "./app-header";
import { NewProjectDialog } from "./new-project-dialog";
import { Welcome } from "./welcome";
import { useWorkspace, WorkspaceProvider } from "./workspace-context";

const NARROW_SCREEN_QUERY = "(max-width: 767px)";

export function Workspace() {
  return (
    <ConfirmProvider>
      <WorkspaceProvider>
        <CursorProvider>
          <WorkspaceLayout />
        </CursorProvider>
      </WorkspaceProvider>
    </ConfirmProvider>
  );
}

function WorkspaceLayout() {
  const { state, actions, canOpenDirectory } = useWorkspace();
  const { connection, recheck } = useBackendHealth();
  const sidebarRef = usePanelRef();
  const problemsRef = usePanelRef();
  const folderInputRef = useRef<HTMLInputElement>(null);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [problemsOpen, setProblemsOpen] = useState(true);
  const [newProjectOpen, setNewProjectOpen] = useState(false);
  const hasProject = state.project !== null;

  // `webkitdirectory` is not in React's input typings; set it on the element.
  useEffect(() => {
    folderInputRef.current?.setAttribute("webkitdirectory", "");
  }, []);

  // Start with the explorer collapsed on narrow screens so the editor keeps its space.
  useEffect(() => {
    if (hasProject && window.matchMedia(NARROW_SCREEN_QUERY).matches)
      sidebarRef.current?.collapse();
  }, [hasProject, sidebarRef]);

  const toggleSidebar = useCallback(() => {
    const panel = sidebarRef.current;
    if (!panel) return;
    if (panel.isCollapsed()) panel.expand();
    else panel.collapse();
  }, [sidebarRef]);

  const toggleProblems = useCallback(() => {
    const panel = problemsRef.current;
    if (!panel) return;
    if (panel.isCollapsed()) panel.expand();
    else panel.collapse();
  }, [problemsRef]);

  const openFolder = useCallback(() => {
    if (canOpenDirectory) void actions.openDirectory();
    else folderInputRef.current?.click();
  }, [actions, canOpenDirectory]);

  // Global shortcuts that must work outside the editor too.
  const activePath = state.activePath;
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (!(event.ctrlKey || event.metaKey) || event.altKey) return;
      const key = event.key.toLowerCase();
      if (key === "s" && !event.shiftKey) {
        event.preventDefault(); // never show the browser's "Save page" dialog
        if (activePath) void actions.saveFile(activePath);
      } else if (key === "b" && !event.shiftKey) {
        event.preventDefault();
        toggleSidebar();
      } else if (key === "j" && !event.shiftKey) {
        event.preventDefault();
        toggleProblems();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [actions, activePath, toggleProblems, toggleSidebar]);

  return (
    <div className="flex h-dvh min-h-0 flex-col">
      <AppHeader
        sidebarOpen={hasProject && sidebarOpen}
        onToggleSidebar={toggleSidebar}
        onNewProject={() => setNewProjectOpen(true)}
        onOpenFolder={openFolder}
      />

      <main className="min-h-0 flex-1">
        {hasProject ? (
          <Group orientation="horizontal" className="h-full">
            <Panel
              id="explorer"
              panelRef={sidebarRef}
              collapsible
              defaultSize="20%"
              minSize={170}
              maxSize="45%"
              onResize={(size) => setSidebarOpen(size.inPixels > 0)}
            >
              <ProjectExplorer key={state.project?.id} />
            </Panel>
            <Separator />
            <Panel id="main" minSize={240}>
              <Group orientation="vertical" className="h-full">
                <Panel id="editor" minSize={120}>
                  <EditorArea />
                </Panel>
                <Separator />
                <Panel
                  id="problems"
                  panelRef={problemsRef}
                  collapsible
                  defaultSize="24%"
                  minSize={72}
                  maxSize="70%"
                  onResize={(size) => setProblemsOpen(size.inPixels > 0)}
                >
                  {problemsOpen && <ProblemsPanel onClose={toggleProblems} />}
                </Panel>
              </Group>
            </Panel>
          </Group>
        ) : (
          <Welcome onNewProject={() => setNewProjectOpen(true)} onOpenFolder={openFolder} />
        )}
      </main>

      <StatusBar
        connection={connection}
        onRecheck={() => void recheck()}
        onToggleProblems={toggleProblems}
      />

      <NewProjectDialog
        open={newProjectOpen}
        onClose={() => setNewProjectOpen(false)}
        onCreate={(name) => {
          setNewProjectOpen(false);
          void actions.createProject(name);
        }}
      />
      <input
        ref={folderInputRef}
        type="file"
        multiple
        hidden
        aria-hidden
        tabIndex={-1}
        onChange={(event) => {
          const files = event.target.files;
          if (files) void actions.openSnapshot(files);
          event.target.value = "";
        }}
      />
    </div>
  );
}
