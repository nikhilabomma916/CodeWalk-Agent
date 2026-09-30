"use client";

import { Settings } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

import { IconButton } from "@/components/ui/icon-button";
import type { EditorSettings } from "@/features/workspace/state";

const FONT_SIZES = [11, 12, 13, 14, 15, 16, 18, 20, 22, 24];
const TAB_SIZES = [2, 4, 8];

interface EditorSettingsMenuProps {
  settings: EditorSettings;
  onChange(settings: Partial<EditorSettings>): void;
}

export function EditorSettingsMenu({ settings, onChange }: EditorSettingsMenuProps) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const panelId = useId();

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => event.key === "Escape" && setOpen(false);
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  const selectClass = "h-6 rounded border border-border bg-surface-sunken px-1 text-xs text-fg";
  const rowClass = "flex items-center justify-between gap-4 py-1 text-xs text-fg-muted";

  return (
    <div ref={containerRef} className="relative">
      <IconButton
        label="Editor settings"
        active={open}
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((value) => !value)}
      >
        <Settings aria-hidden className="size-4" />
      </IconButton>
      {open && (
        <div
          id={panelId}
          role="group"
          aria-label="Editor settings"
          className="absolute top-full right-0 z-50 mt-1 w-56 rounded-md border border-border bg-surface-raised p-3 shadow-xl"
        >
          <label className={rowClass}>
            Font size
            <select
              className={selectClass}
              value={settings.fontSize}
              onChange={(event) => onChange({ fontSize: Number(event.target.value) })}
            >
              {FONT_SIZES.map((size) => (
                <option key={size} value={size}>
                  {size}px
                </option>
              ))}
            </select>
          </label>
          <label className={rowClass}>
            Tab size
            <select
              className={selectClass}
              value={settings.tabSize}
              onChange={(event) => onChange({ tabSize: Number(event.target.value) })}
            >
              {TAB_SIZES.map((size) => (
                <option key={size} value={size}>
                  {size}
                </option>
              ))}
            </select>
          </label>
          <label className={rowClass}>
            Word wrap
            <input
              type="checkbox"
              checked={settings.wordWrap}
              onChange={(event) => onChange({ wordWrap: event.target.checked })}
              className="accent-accent"
            />
          </label>
          <label className={rowClass}>
            Minimap
            <input
              type="checkbox"
              checked={settings.minimap}
              onChange={(event) => onChange({ minimap: event.target.checked })}
              className="accent-accent"
            />
          </label>
        </div>
      )}
    </div>
  );
}
