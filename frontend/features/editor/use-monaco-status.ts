"use client";

import { loader } from "@monaco-editor/react";
import { useEffect, useState } from "react";

import "./monaco-setup";

export type MonacoStatus = "loading" | "ready" | "error";

/**
 * Tracks loading of the Monaco runtime. @monaco-editor/react only logs load
 * failures, which would leave a spinner forever; this lets the UI show an error.
 */
export function useMonacoStatus(): MonacoStatus {
  const [status, setStatus] = useState<MonacoStatus>("loading");

  useEffect(() => {
    let active = true;
    loader
      .init()
      .then(() => active && setStatus("ready"))
      .catch((error: unknown) => {
        const cancelled =
          typeof error === "object" &&
          error !== null &&
          "type" in error &&
          error.type === "cancelation";
        if (active && !cancelled) setStatus("error");
      });
    return () => {
      active = false;
    };
  }, []);

  return status;
}
