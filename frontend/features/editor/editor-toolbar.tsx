"use client";

import { Redo2, Save, Search, Undo2, WandSparkles, WrapText } from "lucide-react";
import type { editor } from "monaco-editor";
import { useEffect, useState } from "react";

import { IconButton } from "@/components/ui/icon-button";
import { LANGUAGES, isLanguageId, languageLabel, type LanguageId } from "@/lib/languages";

interface EditorToolbarProps {
  editor: editor.IStandaloneCodeEditor | null;
  path: string;
  detectedLanguage: LanguageId;
  languageOverride?: LanguageId;
  dirty: boolean;
  readOnly: boolean;
  saving: boolean;
  wordWrap: boolean;
  onSave(): void;
  onLanguageChange(language: LanguageId | null): void;
  onToggleWordWrap(): void;
}

interface EditorCapabilities {
  canUndo: boolean;
  canRedo: boolean;
  canFormat: boolean;
}

const NO_CAPABILITIES: EditorCapabilities = { canUndo: false, canRedo: false, canFormat: false };

/** Reads what the current Monaco model supports, refreshing when content, model, or language changes. */
function useEditorCapabilities(instance: editor.IStandaloneCodeEditor | null): EditorCapabilities {
  const [capabilities, setCapabilities] = useState(NO_CAPABILITIES);

  useEffect(() => {
    if (!instance) return;
    const refresh = () => {
      const model = instance.getModel();
      const next: EditorCapabilities = {
        canUndo: !!model?.canUndo(),
        canRedo: !!model?.canRedo(),
        canFormat: !!instance.getAction("editor.action.formatDocument")?.isSupported(),
      };
      setCapabilities((current) =>
        current.canUndo === next.canUndo &&
        current.canRedo === next.canRedo &&
        current.canFormat === next.canFormat
          ? current
          : next,
      );
    };
    // Initial read is deferred a tick; language features also register
    // asynchronously after a language first loads, hence the second read.
    const initial = setTimeout(refresh, 0);
    const timer = setTimeout(refresh, 500);
    const subscriptions = [
      instance.onDidChangeModelContent(refresh),
      instance.onDidChangeModel(refresh),
      instance.onDidChangeModelLanguage(() => setTimeout(refresh, 300)),
      instance.onDidFocusEditorText(refresh),
    ];
    return () => {
      clearTimeout(initial);
      clearTimeout(timer);
      subscriptions.forEach((subscription) => subscription.dispose());
    };
  }, [instance]);

  return instance ? capabilities : NO_CAPABILITIES;
}

export function EditorToolbar({
  editor: instance,
  path,
  detectedLanguage,
  languageOverride,
  dirty,
  readOnly,
  saving,
  wordWrap,
  onSave,
  onLanguageChange,
  onToggleWordWrap,
}: EditorToolbarProps) {
  const { canUndo, canRedo, canFormat } = useEditorCapabilities(instance);

  const run = (actionId: string) => {
    if (!instance) return;
    instance.focus();
    void instance.getAction(actionId)?.run();
  };

  return (
    <div
      role="toolbar"
      aria-label="Editor actions"
      className="flex h-8 shrink-0 items-center gap-0.5 border-b border-border bg-surface px-2"
    >
      <span
        className="mr-2 min-w-0 flex-1 truncate font-mono text-[11px] text-fg-muted"
        title={path}
      >
        {path}
      </span>
      <IconButton
        label={readOnly ? "Save (read-only project)" : "Save"}
        shortcut="Ctrl+S"
        onClick={onSave}
        disabled={readOnly || !dirty || saving}
      >
        <Save aria-hidden className="size-4" />
      </IconButton>
      <span aria-hidden className="mx-1 h-4 w-px bg-border" />
      <IconButton
        label="Undo"
        shortcut="Ctrl+Z"
        onClick={() => instance?.trigger("toolbar", "undo", null)}
        disabled={!canUndo}
      >
        <Undo2 aria-hidden className="size-4" />
      </IconButton>
      <IconButton
        label="Redo"
        shortcut="Ctrl+Shift+Z"
        onClick={() => instance?.trigger("toolbar", "redo", null)}
        disabled={!canRedo}
      >
        <Redo2 aria-hidden className="size-4" />
      </IconButton>
      <IconButton
        label="Find"
        shortcut="Ctrl+F"
        onClick={() => run("actions.find")}
        disabled={!instance}
      >
        <Search aria-hidden className="size-4" />
      </IconButton>
      {canFormat && (
        <IconButton
          label="Format document"
          shortcut="Shift+Alt+F"
          onClick={() => run("editor.action.formatDocument")}
        >
          <WandSparkles aria-hidden className="size-4" />
        </IconButton>
      )}
      <IconButton label="Toggle word wrap" active={wordWrap} onClick={onToggleWordWrap}>
        <WrapText aria-hidden className="size-4" />
      </IconButton>
      <span aria-hidden className="mx-1 h-4 w-px bg-border" />
      <label className="sr-only" htmlFor="language-select">
        Language
      </label>
      <select
        id="language-select"
        value={languageOverride ?? "auto"}
        onChange={(event) => {
          const value = event.target.value;
          onLanguageChange(isLanguageId(value) ? value : null);
        }}
        className="h-6 max-w-40 rounded border border-border bg-surface-raised px-1.5 text-xs text-fg hover:border-border-strong"
      >
        <option value="auto">Auto ({languageLabel(detectedLanguage)})</option>
        {LANGUAGES.map((language) => (
          <option key={language.id} value={language.id}>
            {language.label}
          </option>
        ))}
      </select>
    </div>
  );
}
