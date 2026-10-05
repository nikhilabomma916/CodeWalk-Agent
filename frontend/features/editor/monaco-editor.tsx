"use client";

import Editor from "@monaco-editor/react";
import type { editor } from "monaco-editor";
import { useEffect, useRef } from "react";

import { useTheme } from "@/features/theme/theme-context";
import type { EditorSettings, ReplaceRequest, RevealRequest } from "@/features/workspace/state";
import type { Diagnostic } from "@/types/diagnostics";

import type { SelectionInfo } from "./cursor-context";

import {
  ANALYSIS_MARKER_OWNER,
  configureMonaco,
  modelUri,
  MONO_FONT_STACK,
  monacoTheme,
  toMarkers,
  type Monaco,
  pathFromModelUri,
} from "./monaco-setup";
import { inlineCompletionConfig } from "./inline-completion-provider";

export interface MonacoEditorProps {
  projectId: string;
  path: string;
  /** Used only when this file's model is first created. */
  initialContent: string;
  language: string;
  settings: EditorSettings;
  readOnly: boolean;
  /** AI ghost text while typing (the setting is on and AI is available). */
  aiCompletions?: boolean;
  openPaths: readonly string[];
  /** Diagnostics per file path; rendered as markers on the matching models. */
  diagnostics: Readonly<Record<string, readonly Diagnostic[]>>;
  reveal: RevealRequest | null;
  /** Content replacement to apply to an open file's model (keeps undo history). */
  replace?: ReplaceRequest | null;
  onChange(path: string, content: string): void;
  onSave(path: string): void;
  onCursor(
    line: number,
    column: number,
    selectedChars: number,
    selection: SelectionInfo | null,
  ): void;
  onReady(editor: editor.IStandaloneCodeEditor | null): void;
}

/**
 * Monaco keeps one model per open file (content, undo stack, markers).
 * Models are created lazily by @monaco-editor/react from `path` and disposed
 * here once their tab closes.
 */
// Reveal requests carry an increasing nonce; each is applied once, even if the editor remounts.
let lastAppliedReveal = 0;

/** Moves the caret to a requested position, scrolls it into view, and focuses the editor. */
function applyReveal(instance: editor.IStandaloneCodeEditor, reveal: RevealRequest): void {
  lastAppliedReveal = Math.max(lastAppliedReveal, reveal.nonce);
  const position = { lineNumber: reveal.line, column: reveal.column };
  instance.setPosition(position);
  instance.revealPositionInCenter(position);
  instance.focus();
}

export default function MonacoEditor(props: MonacoEditorProps) {
  const { theme } = useTheme();
  const { projectId, path, initialContent, language, settings, readOnly, openPaths, reveal } =
    props;
  const { diagnostics } = props;
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
    // Ctrl+Space: ask for an AI suggestion now (ghost text) as well as the usual suggestion list.
    instance.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.Space, () => {
      if (latest.current.aiCompletions)
        instance.trigger("keyboard", "editor.action.inlineSuggest.trigger", {});
      instance.trigger("keyboard", "editor.action.triggerSuggest", {});
    });

    const reportCursor = () => {
      const position = instance.getPosition();
      const model = instance.getModel();
      if (!position || !model) return;
      const selectedChars = (instance.getSelections() ?? []).reduce(
        (total, selection) => total + model.getValueLengthInRange(selection),
        0,
      );
      const primary = instance.getSelection();
      const selection =
        primary && !primary.isEmpty()
          ? {
              startLine: primary.startLineNumber,
              startColumn: primary.startColumn,
              endLine: primary.endLineNumber,
              endColumn: primary.endColumn,
            }
          : null;
      latest.current.onCursor(position.lineNumber, position.column, selectedChars, selection);
    };
    instance.onDidChangeCursorSelection(reportCursor);
    instance.onDidChangeModel(reportCursor);
    reportCursor();

    latest.current.onReady(instance);
    // A reveal requested before the editor existed (e.g. a search result opened while no file was
    // open) was skipped by the effect below, which only runs on new requests: apply it now.
    const pending = latest.current.reveal;
    if (pending && pending.path === latest.current.path && pending.nonce > lastAppliedReveal)
      applyReveal(instance, pending);
    else if (!document.activeElement?.closest('[role="tree"]')) instance.focus();
  };

  // The ghost-text provider is global: point it at this project and switch it on or off.
  const aiCompletions = Boolean(props.aiCompletions) && !readOnly;
  useEffect(() => {
    inlineCompletionConfig.enabled = aiCompletions;
    inlineCompletionConfig.pathFor = (uri) => pathFromModelUri(projectId, uri);
    return () => {
      inlineCompletionConfig.enabled = false;
    };
  }, [aiCompletions, projectId]);

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

  // Render backend diagnostics as markers on every open model.
  useEffect(() => {
    const monaco = monacoRef.current;
    if (!monaco) return;
    for (const openPath of openPaths) {
      const model = monaco.editor.getModel(monaco.Uri.parse(modelUri(projectId, openPath)));
      if (model) {
        monaco.editor.setModelMarkers(
          model,
          ANALYSIS_MARKER_OWNER,
          toMarkers(monaco, diagnostics[openPath] ?? []),
        );
      }
    }
  }, [diagnostics, openPaths, projectId, path]);

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

  // Apply a requested content replacement to that file's model, as one undoable edit. The model
  // may belong to a tab that is not shown; files without a model pick the content up from the buffer.
  const replace = props.replace;
  useEffect(() => {
    const monaco = monacoRef.current;
    if (!monaco || !replace) return;
    const model = monaco.editor.getModel(monaco.Uri.parse(modelUri(projectId, replace.path)));
    if (!model || model.getValue() === replace.content) return;
    model.pushEditOperations(
      [],
      [{ range: model.getFullModelRange(), text: replace.content }],
      () => null,
    );
    model.pushStackElement();
  }, [replace, projectId]);

  // Navigate to a requested position (e.g. from the Problems panel).
  useEffect(() => {
    const instance = editorRef.current;
    if (!instance || !reveal || reveal.path !== path) return;
    applyReveal(instance, reveal);
  }, [reveal, path]);

  return (
    <Editor
      path={modelUri(projectId, path)}
      defaultValue={initialContent}
      language={language}
      theme={monacoTheme(theme)}
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
        readOnly,
        readOnlyMessage: { value: "This project is linked to a server folder and is read-only." },
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
        inlineSuggest: { enabled: aiCompletions, showToolbar: "onHover" },
        fixedOverflowWidgets: true,
        padding: { top: 8 },
      }}
    />
  );
}
