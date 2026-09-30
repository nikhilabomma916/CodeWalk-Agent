"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";

export interface ConfirmAction<T extends string> {
  value: T;
  label: string;
  variant?: "primary" | "danger" | "default";
}

export interface ConfirmOptions<T extends string> {
  title: string;
  message: ReactNode;
  actions: ConfirmAction<T>[];
  /** Value resolved when the dialog is dismissed with Escape. */
  cancelValue: T;
}

type ConfirmFn = <T extends string>(options: ConfirmOptions<T>) => Promise<T>;

const ConfirmContext = createContext<ConfirmFn | null>(null);

interface PendingConfirm {
  options: ConfirmOptions<string>;
  resolve: (value: string) => void;
}

const VARIANT_CLASSES: Record<NonNullable<ConfirmAction<string>["variant"]>, string> = {
  primary: "bg-accent text-white hover:bg-accent-strong",
  danger: "bg-danger/90 text-white hover:bg-danger",
  default: "bg-surface-raised text-fg hover:bg-surface-hover border border-border",
};

/** Promise-based modal confirmation built on the native <dialog> element (focus trap + Escape). */
export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [pending, setPending] = useState<PendingConfirm | null>(null);
  const dialogRef = useRef<HTMLDialogElement>(null);

  const confirm = useCallback<ConfirmFn>(
    <T extends string>(options: ConfirmOptions<T>) =>
      new Promise<T>((resolve) => {
        setPending({ options, resolve: resolve as (value: string) => void });
      }),
    [],
  );

  useEffect(() => {
    const dialog = dialogRef.current;
    if (pending && dialog && !dialog.open) dialog.showModal();
  }, [pending]);

  const settle = (value: string) => {
    pending?.resolve(value);
    setPending(null);
    dialogRef.current?.close();
  };

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      {pending && (
        <dialog
          ref={dialogRef}
          aria-labelledby="confirm-title"
          className="m-auto w-[min(28rem,calc(100vw-2rem))] rounded-md border border-border bg-surface p-0 text-fg shadow-xl backdrop:bg-black/60"
          onCancel={(event) => {
            event.preventDefault();
            settle(pending.options.cancelValue);
          }}
        >
          <div className="p-4">
            <h2 id="confirm-title" className="text-sm font-semibold">
              {pending.options.title}
            </h2>
            <div className="mt-2 text-sm text-fg-muted">{pending.options.message}</div>
          </div>
          <div className="flex flex-wrap justify-end gap-2 border-t border-border bg-surface-sunken px-4 py-3">
            {pending.options.actions.map((action, index) => (
              <button
                key={action.value}
                type="button"
                autoFocus={index === 0}
                onClick={() => settle(action.value)}
                className={`rounded px-3 py-1.5 text-xs font-medium ${VARIANT_CLASSES[action.variant ?? "default"]}`}
              >
                {action.label}
              </button>
            ))}
          </div>
        </dialog>
      )}
    </ConfirmContext.Provider>
  );
}

export function useConfirm(): ConfirmFn {
  const confirm = useContext(ConfirmContext);
  if (!confirm) throw new Error("useConfirm must be used inside <ConfirmProvider>");
  return confirm;
}
