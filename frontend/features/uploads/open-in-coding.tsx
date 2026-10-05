"use client";

import { FilePenLine, Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { buttonClass } from "@/components/ui/page-frame";
import { IconButton } from "@/components/ui/icon-button";
import { codingHref } from "@/features/workspace/use-coding-deep-link";
import { isApiError } from "@/services/api/errors";
import { createEditableCopy, type ServerProject } from "@/services/api/projects";

/**
 * Upload → Import → editable Coding project: creates a copy of the upload's files as a normal
 * project (the upload is kept unchanged) and opens it in Coding.
 */
export function useOpenInCoding(upload: Pick<ServerProject, "id" | "name">) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const open = async () => {
    setBusy(true);
    setError(null);
    try {
      const copy = await createEditableCopy(upload.id);
      router.push(codingHref(copy.id));
    } catch (e) {
      setError(isApiError(e) ? e.message : `“${upload.name}” could not be imported into Coding.`);
      setBusy(false);
    }
  };
  return { open, busy, error };
}

const HINT =
  "Creates an editable Coding project with a copy of these files; the upload stays unchanged.";

/** Page action on an upload's detail page. */
export function OpenInCodingButton({ upload }: { upload: Pick<ServerProject, "id" | "name"> }) {
  const { open, busy, error } = useOpenInCoding(upload);
  return (
    <>
      <button
        type="button"
        className={buttonClass.primary}
        disabled={busy}
        title={HINT}
        onClick={() => void open()}
      >
        {busy ? (
          <Loader2 aria-hidden className="size-3.5 animate-spin" />
        ) : (
          <FilePenLine aria-hidden className="size-3.5" />
        )}
        {busy ? "Importing…" : "Open in Coding"}
      </button>
      {error && (
        <span role="alert" className="text-xs text-danger">
          {error}
        </span>
      )}
    </>
  );
}

/** Row action in the Uploads list. */
export function OpenInCodingIconButton({ upload }: { upload: Pick<ServerProject, "id" | "name"> }) {
  const { open, busy, error } = useOpenInCoding(upload);
  return (
    <>
      {error && (
        <span role="alert" className="max-w-48 truncate text-xs text-danger" title={error}>
          {error}
        </span>
      )}
      <IconButton
        label={`Open ${upload.name} in Coding (editable copy)`}
        onClick={() => void open()}
        disabled={busy}
      >
        {busy ? (
          <Loader2 aria-hidden className="size-4 animate-spin" />
        ) : (
          <FilePenLine aria-hidden className="size-4" />
        )}
      </IconButton>
    </>
  );
}
