import { MAX_EDITABLE_FILE_BYTES, SourceError } from "./types";

const BINARY_SNIFF_BYTES = 8000;

/** Decodes file bytes as UTF-8 text, rejecting binary and oversized files. */
export async function decodeTextFile(file: Blob, path: string): Promise<string> {
  if (file.size > MAX_EDITABLE_FILE_BYTES) {
    throw new SourceError(
      "too-large",
      `${path} is ${(file.size / 1024 / 1024).toFixed(1)} MB; files over ${MAX_EDITABLE_FILE_BYTES / 1024 / 1024} MB are not opened in the editor.`,
    );
  }
  const bytes = new Uint8Array(await file.arrayBuffer());
  if (bytes.subarray(0, BINARY_SNIFF_BYTES).includes(0)) {
    throw new SourceError("binary", `${path} appears to be a binary file.`);
  }
  try {
    return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch (cause) {
    throw new SourceError("binary", `${path} is not valid UTF-8 text.`, { cause });
  }
}
