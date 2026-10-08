"use client";

import type { editor } from "monaco-editor";
import dynamic from "next/dynamic";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { StateMessage } from "@/components/ui/state-message";
import { useAgent } from "@/features/agent/agent-context";
import { AgentReview } from "@/features/agent/agent-review";
import { useAIAssist } from "@/features/ai/ai-assist-context";
import { FixReview, FixStatusBanner } from "@/features/ai/fix-review";
import { useLiveAnalysis } from "@/features/analysis/use-live-analysis";
import { isDirty } from "@/features/workspace/state";
import { useWorkspaceLayout } from "@/features/workspace/layout-context";
import { useWorkspace } from "@/features/workspace/workspace-context";
import { detectLanguage } from "@/lib/languages";
import type { Diagnostic } from "@/types/diagnostics";

import { useSetCursor, type SelectionInfo } from "./cursor-context";
import { editorAIHandler, SELECTION_ACTIONS } from "./editor-ai-actions";
import { EditorTabs } from "./editor-tabs";
import { EditorToolbar } from "./editor-toolbar";
import { pathFromModelUri } from "./monaco-setup";
import { useMonacoStatus } from "./use-monaco-status";

const MonacoEditor = dynamic(() => import("./monaco-editor"), {
  ssr: false,
  loading: () => <StateMessage title="Loading editor…" />,
});

export function EditorArea() {
  const { state, actions } = useWorkspace();
  const { project, openPaths, activePath, buffers, editorSettings, reveal, replace, diagnostics } =
    state;
  const setCursor = useSetCursor();
  const monacoStatus = useMonacoStatus();
  const { status: aiStatus, explain, requestFix } = useAIAssist();
  const aiAvailable = aiStatus.state === "ready" && aiStatus.data.available;
  const agent = useAgent();
  const layout = useWorkspaceLayout();

  // AI actions started in the editor (light bulb on a problem, right-click on a selection).
  const latestRef = useRef({ state, agent, layout, explain, requestFix });
  useEffect(() => {
    latestRef.current = { state, agent, layout, explain, requestFix };
  });
  useEffect(() => {
    editorAIHandler.current = (request) => {
      const current = latestRef.current;
      if (request.kind === "diagnostic") {
        const projectId = current.state.project?.id;
        const path = projectId ? pathFromModelUri(projectId, request.uri) : null;
        if (!path) return;
        const diagnostic = Object.values(current.state.diagnostics)
          .flatMap((byFile) => byFile[path] ?? [])
          .find(
            (d) =>
              d.line === request.line &&
              d.column === request.column &&
              d.message === request.message,
          );
        if (!diagnostic) return;
        if (request.action === "explain") {
          current.layout.showProblems(); // the explanation opens next to the Problems list
          void current.explain(diagnostic);
        } else {
          void current.requestFix(diagnostic); // reviewed in a diff over the editor
        }
        return;
      }
      const action = SELECTION_ACTIONS.find((a) => a.id === request.action);
      if (!action) return;
      current.layout.showAgent();
      if (action.message)
        void current.agent.ask(action.message, {
          includeFile: true,
          includeSelection: true,
          mode: action.mode,
        });
      else if (action.draft) current.agent.setDraft(action.draft);
    };
    return () => {
      editorAIHandler.current = null;
    };
  }, []);
  const [editorInstance, setEditorInstance] = useState<editor.IStandaloneCodeEditor | null>(null);

  const dirtyPaths = useMemo(
    () => new Set(openPaths.filter((path) => isDirty(buffers[path]))),
    [openPaths, buffers],
  );

  const handleCursor = useCallback(
    (line: number, column: number, selectedChars: number, selection: SelectionInfo | null) =>
      setCursor({ line, column, selectedChars, selection }),
    [setCursor],
  );

  const handleReady = useCallback(
    (instance: editor.IStandaloneCodeEditor | null) => {
      setEditorInstance(instance);
      if (!instance) setCursor(null);
    },
    [setCursor],
  );

  // All producers' diagnostics, per file, for the editor markers.
  const diagnosticsByPath = useMemo(() => {
    const merged: Record<string, Diagnostic[]> = {};
    for (const byFile of Object.values(diagnostics)) {
      for (const [path, items] of Object.entries(byFile)) {
        (merged[path] ??= []).push(...items);
      }
    }
    return merged;
  }, [diagnostics]);

  useLiveAnalysis(activePath, activePath ? buffers[activePath] : undefined, actions);

  const handleClose = useCallback((path: string) => void actions.closeTab(path), [actions]);

  // Keep Monaco mounted on the previously shown file while another one loads:
  // unmounting would dispose every model and lose the open files' undo history.
  const [shownPath, setShownPath] = useState<string | null>(null);
  const activeReady = !!activePath && buffers[activePath]?.status === "ready";
  if (activeReady && shownPath !== activePath) setShownPath(activePath);
  const editorPath =
    activeReady && activePath
      ? activePath
      : shownPath && openPaths.includes(shownPath) && buffers[shownPath]?.status === "ready"
        ? shownPath
        : null;

  if (!project) return null;

  const buffer = activePath ? buffers[activePath] : undefined;

  if (openPaths.length === 0 || !activePath) {
    return (
      <StateMessage title="No file open">
        Select a file in the explorer to open it. Use <kbd className="font-mono">Ctrl+S</kbd> to
        save.
      </StateMessage>
    );
  }

  const detected = detectLanguage(activePath);

  let overlay: React.ReactNode = null;
  if (monacoStatus === "error") {
    overlay = (
      <StateMessage tone="error" title="The code editor failed to load.">
        Monaco assets could not be loaded from <code className="font-mono">/monaco/vs</code>. Run{" "}
        <code className="font-mono">npm run dev</code> or{" "}
        <code className="font-mono">npm run build</code> (which copy the assets) and reload.
      </StateMessage>
    );
  } else if (!buffer || buffer.status === "loading") {
    overlay = <StateMessage title={`Opening ${activePath}…`} />;
  } else if (buffer.status === "error") {
    overlay = (
      <StateMessage
        tone="error"
        title="Unable to open file."
        action={
          <button
            type="button"
            onClick={() => void actions.openFile(activePath)}
            className="mt-1 rounded border border-border px-2 py-1 text-xs hover:bg-surface-hover"
          >
            Retry
          </button>
        }
      >
        {buffer.loadError}
      </StateMessage>
    );
  }

  const editorBuffer = editorPath ? buffers[editorPath] : undefined;
  const body =
    editorPath && editorBuffer && monacoStatus !== "error" ? (
      <MonacoEditor
        projectId={project.id}
        path={editorPath}
        initialContent={editorBuffer.content}
        language={editorBuffer.languageOverride ?? detectLanguage(editorPath)}
        settings={editorSettings}
        readOnly={project.readOnly}
        aiCompletions={editorSettings.aiCompletions && aiAvailable}
        openPaths={openPaths}
        diagnostics={diagnosticsByPath}
        reveal={reveal}
        replace={replace}
        onChange={actions.editFile}
        onSave={(path) => void actions.saveFile(path)}
        onCursor={handleCursor}
        onReady={handleReady}
      />
    ) : null;

  const ready = buffer?.status === "ready";

  return (
    <div className="flex h-full min-h-0 flex-col bg-surface">
      <EditorTabs
        openPaths={openPaths}
        activePath={activePath}
        dirtyPaths={dirtyPaths}
        onActivate={actions.activateTab}
        onClose={handleClose}
      />
      {ready && (
        <EditorToolbar
          editor={editorInstance}
          path={activePath}
          detectedLanguage={detected}
          languageOverride={buffer.languageOverride}
          dirty={dirtyPaths.has(activePath)}
          readOnly={project.readOnly}
          saving={buffer.saving}
          wordWrap={editorSettings.wordWrap}
          onSave={() => void actions.saveFile(activePath)}
          onLanguageChange={(next) => actions.setLanguage(activePath, next)}
          onToggleWordWrap={() => actions.updateSettings({ wordWrap: !editorSettings.wordWrap })}
        />
      )}
      {buffer?.saveError && (
        <div
          role="alert"
          className="shrink-0 border-b border-danger/40 bg-danger/10 px-3 py-1 text-xs text-danger"
        >
          Save failed: {buffer.saveError}
        </div>
      )}
      <div className="relative min-h-0 flex-1">
        {body}
        {overlay && <div className="absolute inset-0 z-10 bg-surface">{overlay}</div>}
        {ready && <FixStatusBanner path={activePath} />}
        {ready && <FixReview path={activePath} />}
        {ready && <AgentReview path={activePath} />}
      </div>
    </div>
  );
}
