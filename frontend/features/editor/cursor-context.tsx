"use client";

import {
  createContext,
  useContext,
  useState,
  type Dispatch,
  type ReactNode,
  type SetStateAction,
} from "react";

export interface CursorInfo {
  line: number;
  column: number;
  selectedChars: number;
}

// Cursor updates are frequent, so they live in their own context: only the
// status bar re-renders when the caret moves.
const CursorStateContext = createContext<CursorInfo | null>(null);
const CursorSetterContext = createContext<Dispatch<SetStateAction<CursorInfo | null>> | null>(null);

export function CursorProvider({ children }: { children: ReactNode }) {
  const [cursor, setCursor] = useState<CursorInfo | null>(null);
  return (
    <CursorSetterContext.Provider value={setCursor}>
      <CursorStateContext.Provider value={cursor}>{children}</CursorStateContext.Provider>
    </CursorSetterContext.Provider>
  );
}

export function useCursor(): CursorInfo | null {
  return useContext(CursorStateContext);
}

export function useSetCursor(): Dispatch<SetStateAction<CursorInfo | null>> {
  const setter = useContext(CursorSetterContext);
  if (!setter) throw new Error("useSetCursor must be used inside <CursorProvider>");
  return setter;
}
