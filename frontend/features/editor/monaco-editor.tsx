"use client";

import Editor from "@monaco-editor/react";
import type { editor } from "monaco-editor";
import { useEffect, useRef } from "react";

import type { EditorSettings, RevealRequest } from "@/features/workspace/state";
import type { Diagnostic } from "@/types/diagnostics";

import {
  configureMonaco,
  markersToDiagnostics,
  modelUri,
  MONO_FONT_STACK,
  pathFromModelUri,
  THEME_NAME,
  type Monaco,
} from "./monaco-setup";

export interface MonacoEditorProps {
  projectId: string;
  path: string;
  /** Used only when this file's model is first created. */
  initialContent: string;
  language: string;
  settings: EditorSettings;
  openPaths: readonly string[];
  reveal: RevealRequest | null;
  onChange(path: string, content: string): void;
  onSave(path: string): void;
  onCursor(line: number, column: number, selectedChars: number): void;
  onDiagnostics(path: string, diagnostics: Diagnostic[]): void;
  onReady(editor: editor.IStandaloneCodeEditor | null): void;
}

/**
 * Monaco keeps one model per open file (content, undo stack, markers).
 * Models are created lazily by @monaco-editor/react from `path` and disposed
 * here once their tab closes.
 */
export default function MonacoEditor(props: MonacoEditorProps) {
  const { projectId, path, initialContent, language, settings, openPaths, reveal } = props;
  const editorRef = useRef<editor.IStandaloneCodeEditor | null>(null);
  const monacoRef = useRef<Monaco | null>(null);
  // Callbacks registered with Monaco once at mount read the latest props through this ref.
  const latest = useRef(props);
  useEffect(() => {
    latest.current = props;
  });

  const handleMount = (instance: editor.IStandaloneCodeEditor, monaco: Monaco) => {
    editorRef.current = instance;
    monacoRef.current = monaco;

    instance.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => {
      latest.current.onSave(latest.current.path);
    });

    const reportCursor = () => {
      const position = instance.getPosition();
      const model = instance.getModel();
      if (!position || !model) return;
      const selectedChars = (instance.getSelections() ?? []).reduce(
        (total, selection) => total + model.getValueLengthInRange(selection),
        0,
      );
      latest.current.onCursor(position.lineNumber, position.column, selectedChars);
    };
    instance.onDidChangeCursorSelection(reportCursor);
    instance.onDidChangeModel(reportCursor);
    reportCursor();

    const markerSubscription = monaco.editor.onDidChangeMarkers((uris) => {
      for (const uri of uris) {
        const filePath = pathFromModelUri(latest.current.projectId, uri.path);
        if (filePath === null) continue;
        const markers = monaco.editor.getModelMarkers({ resource: uri });
        latest.current.onDiagnostics(filePath, markersToDiagnostics(monaco, filePath, markers));
      }
    });
    instance.onDidDispose(() => markerSubscription.dispose());

    latest.current.onReady(instance);
    if (!document.activeElement?.closest('[role="tree"]')) instance.focus();
  };

  // Dispose models whose tab was closed (or that belong to a previous project).
  useEffect(() => {
    const monaco = monacoRef.current;
    if (!monaco) return;
    const keep = new Set(openPaths.map((openPath) => modelUri(projectId, openPath)));
    for (const model of monaco.editor.getModels()) {
      if (!keep.has(model.uri.toString()) && model !== editorRef.current?.getModel())
        model.dispose();
    }
  }, [openPaths, projectId]);

  // On unmount (no files open) release every model.
  useEffect(
    () => () => {
      latest.current.onReady(null);
      monacoRef.current?.editor.getModels().forEach((model) => model.dispose());
    },
    [],
  );

  // Move focus into the editor when the displayed file changes (tab click, new
  // file), except while the user is keyboard-navigating the explorer tree.
  useEffect(() => {
    if (!document.activeElement?.closest('[role="tree"]')) editorRef.current?.focus();
  }, [path]);

  // Navigate to a requested position (e.g. from the Problems panel).
  useEffect(() => {
    const instance = editorRef.current;
    if (!instance || !reveal || reveal.path !== path) return;
    const position = { lineNumber: reveal.line, column: reveal.column };
    instance.setPosition(position);
    instance.revealPositionInCenter(position);
    instance.focus();
  }, [reveal, path]);

  return (
    <Editor
      path={modelUri(projectId, path)}
      defaultValue={initialContent}
      language={language}
      theme={THEME_NAME}
      keepCurrentModel
      saveViewState
      beforeMount={configureMonaco}
      onMount={handleMount}
      onChange={(value) => props.onChange(path, value ?? "")}
      loading={<span className="text-xs text-fg-muted">Loading editor…</span>}
      options={{
        fontFamily: MONO_FONT_STACK,
        fontSize: settings.fontSize,
        tabSize: settings.tabSize,
        detectIndentation: true,
        wordWrap: settings.wordWrap ? "on" : "off",
        minimap: { enabled: settings.minimap },
        automaticLayout: true,
        scrollBeyondLastLine: false,
        smoothScrolling: true,
        renderWhitespace: "selection",
        bracketPairColorization: { enabled: true },
        guides: { bracketPairs: "active", indentation: true },
        folding: true,
        showFoldingControls: "mouseover",
        matchBrackets: "always",
        stickyScroll: { enabled: true },
        fixedOverflowWidgets: true,
        padding: { top: 8 },
      }}
    />
  );
}
