"use client";

import type { editor } from "monaco-editor";
import dynamic from "next/dynamic";
import { useCallback, useMemo, useState } from "react";

import { StateMessage } from "@/components/ui/state-message";
import { isDirty } from "@/features/workspace/state";
import { useWorkspace } from "@/features/workspace/workspace-context";
import { detectLanguage } from "@/lib/languages";

import { useSetCursor } from "./cursor-context";
import { EditorTabs } from "./editor-tabs";
import { EditorToolbar } from "./editor-toolbar";
import { useMonacoStatus } from "./use-monaco-status";

const MonacoEditor = dynamic(() => import("./monaco-editor"), {
  ssr: false,
  loading: () => <StateMessage title="Loading editor…" />,
});

const EDITOR_DIAGNOSTICS_SOURCE = "editor";

export function EditorArea() {
  const { state, actions } = useWorkspace();
  const { project, openPaths, activePath, buffers, editorSettings, reveal } = state;
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

  const handleDiagnostics = useCallback(
    (path: string, diagnostics: Parameters<typeof actions.replaceDiagnostics>[2]) =>
      actions.replaceDiagnostics(EDITOR_DIAGNOSTICS_SOURCE, path, diagnostics),
    [actions],
  );

  const handleClose = useCallback((path: string) => void actions.closeTab(path), [actions]);

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
  const language = buffer?.languageOverride ?? detected;

  let body: React.ReactNode;
  if (monacoStatus === "error") {
    body = (
      <StateMessage tone="error" title="The code editor failed to load.">
        Monaco assets could not be loaded from <code className="font-mono">/monaco/vs</code>. Run{" "}
        <code className="font-mono">npm run dev</code> or{" "}
        <code className="font-mono">npm run build</code> (which copy the assets) and reload.
      </StateMessage>
    );
  } else if (!buffer || buffer.status === "loading") {
    body = <StateMessage title={`Opening ${activePath}…`} />;
  } else if (buffer.status === "error") {
    body = (
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
  } else {
    body = (
      <MonacoEditor
        projectId={project.id}
        path={activePath}
        initialContent={buffer.content}
        language={language}
        settings={editorSettings}
        openPaths={openPaths}
        reveal={reveal}
        onChange={actions.editFile}
        onSave={(path) => void actions.saveFile(path)}
        onCursor={handleCursor}
        onDiagnostics={handleDiagnostics}
        onReady={handleReady}
      />
    );
  }

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
      <div className="relative min-h-0 flex-1">{body}</div>
    </div>
  );
}
