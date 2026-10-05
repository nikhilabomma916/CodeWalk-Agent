"use client";

import { useEffect, useRef, type KeyboardEvent } from "react";

export interface MenuItem {
  label: string;
  onSelect(): void;
  disabled?: boolean;
  /** Shown as the item's tooltip when disabled. */
  reason?: string | null;
  danger?: boolean;
  separatorBefore?: boolean;
  shortcut?: string;
}

/**
 * A small accessible context menu: arrow keys, Home/End, Enter, Escape; closes on outside click,
 * blur, scroll and resize, and returns focus to `returnFocus`.
 */
export function ContextMenu({
  label,
  x,
  y,
  items,
  onClose,
  returnFocus,
}: {
  label: string;
  x: number;
  y: number;
  items: MenuItem[];
  onClose(): void;
  returnFocus?: HTMLElement | null;
}) {
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const menu = menuRef.current;
    if (!menu) return;
    // Keep the menu inside the viewport.
    const rect = menu.getBoundingClientRect();
    menu.style.left = `${Math.max(4, Math.min(x, window.innerWidth - rect.width - 4))}px`;
    menu.style.top = `${Math.max(4, Math.min(y, window.innerHeight - rect.height - 4))}px`;
    menu.querySelector<HTMLButtonElement>('[role="menuitem"]:not([aria-disabled="true"])')?.focus();
    const close = (event: Event) => {
      if (event.type === "mousedown" && menu.contains(event.target as Node)) return;
      onClose();
    };
    window.addEventListener("mousedown", close);
    window.addEventListener("resize", close);
    window.addEventListener("scroll", close, true);
    return () => {
      window.removeEventListener("mousedown", close);
      window.removeEventListener("resize", close);
      window.removeEventListener("scroll", close, true);
    };
  }, [onClose, x, y]);

  const finish = (item?: MenuItem) => {
    onClose();
    returnFocus?.focus();
    item?.onSelect();
  };

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const buttons = [
      ...(menuRef.current?.querySelectorAll<HTMLButtonElement>(
        '[role="menuitem"]:not([aria-disabled="true"])',
      ) ?? []),
    ];
    const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
    const move = (to: number) => buttons[(to + buttons.length) % buttons.length]?.focus();
    switch (event.key) {
      case "ArrowDown":
        move(index + 1);
        break;
      case "ArrowUp":
        move(index - 1);
        break;
      case "Home":
        move(0);
        break;
      case "End":
        move(buttons.length - 1);
        break;
      case "Escape":
      case "Tab":
        finish();
        break;
      default:
        return;
    }
    event.preventDefault();
  };

  return (
    <div
      ref={menuRef}
      role="menu"
      aria-label={label}
      onKeyDown={onKeyDown}
      onBlur={(event) => {
        if (!menuRef.current?.contains(event.relatedTarget as Node)) onClose();
      }}
      style={{ left: x, top: y }}
      className="fixed z-50 min-w-48 rounded-md border border-border bg-surface py-1 text-[13px] text-fg shadow-xl"
    >
      {items.map((item) => (
        <div key={item.label}>
          {item.separatorBefore && <div role="separator" className="my-1 h-px bg-border" />}
          <button
            type="button"
            role="menuitem"
            aria-disabled={item.disabled || undefined}
            title={item.disabled ? (item.reason ?? undefined) : undefined}
            onClick={() => !item.disabled && finish(item)}
            className={`flex w-full items-center gap-4 px-3 py-1 text-left outline-none focus:bg-accent-muted ${
              item.disabled
                ? "cursor-default text-fg-subtle"
                : item.danger
                  ? "text-danger hover:bg-surface-hover"
                  : "hover:bg-surface-hover"
            }`}
          >
            <span className="flex-1">{item.label}</span>
            {item.shortcut && <span className="text-[11px] text-fg-subtle">{item.shortcut}</span>}
          </button>
        </div>
      ))}
    </div>
  );
}
