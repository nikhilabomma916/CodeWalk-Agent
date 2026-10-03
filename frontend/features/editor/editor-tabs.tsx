"use client";

import { X } from "lucide-react";
import { memo, type KeyboardEvent } from "react";

import { FileIcon } from "@/features/explorer/file-icon";
import { basename } from "@/lib/project-paths";
import { detectLanguage } from "@/lib/languages";

interface EditorTabsProps {
  openPaths: readonly string[];
  activePath: string | null;
  dirtyPaths: ReadonlySet<string>;
  onActivate(path: string): void;
  onClose(path: string): void;
}

export const EditorTabs = memo(function EditorTabs({
  openPaths,
  activePath,
  dirtyPaths,
  onActivate,
  onClose,
}: EditorTabsProps) {
  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>, index: number) => {
    const target =
      event.key === "ArrowRight"
        ? index + 1
        : event.key === "ArrowLeft"
          ? index - 1
          : event.key === "Home"
            ? 0
            : event.key === "End"
              ? openPaths.length - 1
              : null;
    if (target !== null) {
      event.preventDefault();
      const path = openPaths[(target + openPaths.length) % openPaths.length];
      onActivate(path);
      document.getElementById(tabId(path))?.focus();
    } else if (event.key === "Delete") {
      event.preventDefault();
      onClose(openPaths[index]);
    }
  };

  return (
    <div
      role="tablist"
      aria-label="Open files"
      className="flex h-9 shrink-0 [scrollbar-width:thin] overflow-x-auto border-b border-border bg-surface-sunken"
    >
      {openPaths.map((path, index) => {
        const active = path === activePath;
        const dirty = dirtyPaths.has(path);
        return (
          <div
            key={path}
            id={tabId(path)}
            role="tab"
            tabIndex={active ? 0 : -1}
            aria-selected={active}
            title={path}
            onClick={() => onActivate(path)}
            onAuxClick={(event) => event.button === 1 && onClose(path)}
            onKeyDown={(event) => handleKeyDown(event, index)}
            className={`group flex max-w-56 min-w-0 shrink-0 cursor-pointer items-center gap-1.5 border-r border-border pr-1 pl-3 text-xs select-none ${
              active
                ? "bg-surface text-fg shadow-[inset_0_1px_0_var(--color-accent)]"
                : "text-fg-muted hover:bg-surface-raised hover:text-fg"
            }`}
          >
            <FileIcon language={detectLanguage(path)} />
            <span className="truncate">{basename(path)}</span>
            <button
              type="button"
              tabIndex={-1}
              aria-label={
                dirty ? `Close ${basename(path)} (unsaved changes)` : `Close ${basename(path)}`
              }
              title={dirty ? "Unsaved changes — close" : "Close"}
              onClick={(event) => {
                event.stopPropagation();
                onClose(path);
              }}
              className="group/close flex size-5 items-center justify-center rounded hover:bg-surface-hover"
            >
              {dirty ? (
                <>
                  <span
                    aria-hidden
                    className="size-2 rounded-full bg-fg-muted group-hover/close:hidden"
                  />
                  <X aria-hidden className="hidden size-3.5 group-hover/close:block" />
                </>
              ) : (
                <X
                  aria-hidden
                  className={`size-3.5 ${active ? "" : "opacity-0 group-hover:opacity-100"}`}
                />
              )}
            </button>
          </div>
        );
      })}
    </div>
  );
});

export function tabId(path: string): string {
  return `tab-${encodeURIComponent(path)}`;
}
