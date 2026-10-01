"use client";

import type { editor } from "monaco-editor";
import dynamic from "next/dynamic";
import { useCallback, useMemo, useState } from "react";

import { StateMessage } from "@/components/ui/state-message";
import { useLiveAnalysis } from "@/features/analysis/use-live-analysis";
import { isDirty } from "@/features/workspace/state";
import { useWorkspace } from "@/features/workspace/workspace-context";
import { detectLanguage } from "@/lib/languages";
import type { Diagnostic } from "@/types/diagnostics";

import { useSetCursor } from "./cursor-context";
import { EditorTabs } from "./editor-tabs";
import { EditorToolbar } from "./editor-toolbar";
import { useMonacoStatus } from "./use-monaco-status";

const MonacoEditor = dynamic(() => import("./monaco-editor"), {
  ssr: false,
  loading: () => <StateMessage title="Loading editor…" />,
});

export function EditorArea() {
  const { state, actions } = useWorkspace();
  const { project, openPaths, activePath, buffers, editorSettings, reveal, diagnostics } = state;
  const setCursor = useSetCursor();
  const monacoStatus = useMonacoStatus();
  const [editorInstance, setEditorInstance] = useState<editor.IStandaloneCodeEditor | null>(null);

  const dirtyPaths = useMemo(
    () => new Set(openPaths.filter((path) => isDirty(buffers[path]))),
    [openPaths, buffers],
  );

  const handleCursor = useCallback(
    (line: number, column: number, selectedChars: number) =>
      setCursor({ line, column, selectedChars }),
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
        openPaths={openPaths}
        diagnostics={diagnosticsByPath}
        reveal={reveal}
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
      </div>
    </div>
  );
}
