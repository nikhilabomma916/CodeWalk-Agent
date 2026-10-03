import { describe, expect, it } from "vitest";

import { decodeTextFile } from "./decode";
import { LocalSnapshotSource } from "./local-snapshot-source";
import { MemoryProjectSource } from "./memory-source";
import { MAX_EDITABLE_FILE_BYTES, SourceError } from "./types";

function folderFile(relativePath: string, content: BlobPart): File {
  const file = new File([content], relativePath.split("/").pop() ?? "file");
  Object.defineProperty(file, "webkitRelativePath", { value: `my-project/${relativePath}` });
  return file;
}

describe("MemoryProjectSource", () => {
  it("creates, writes, reads, and lists files", async () => {
    const source = new MemoryProjectSource("scratch");
    await source.createFile("src/main.py");
    await source.write("src/main.py", "print('hi')\n");

    expect(await source.read("src/main.py")).toBe("print('hi')\n");
    const { entries } = await source.list();
    expect(entries).toEqual(
      expect.arrayContaining([
        { path: "src", type: "folder" },
        { path: "src/main.py", type: "file" },
      ]),
    );
  });

  it("refuses to overwrite an existing file on create", async () => {
    const source = new MemoryProjectSource("scratch");
    await source.createFile("a.txt");
    await expect(source.createFile("a.txt")).rejects.toMatchObject({ reason: "exists" });
  });
});

describe("LocalSnapshotSource", () => {
  const files = [
    folderFile("src/app.ts", "export const x = 1;\n"),
    folderFile("node_modules/lib/index.js", "ignored"),
    folderFile(".env", "SECRET=1"),
    folderFile(".env.example", "SECRET="),
  ];

  it("derives the folder name and skips dependencies and secrets", async () => {
    expect(LocalSnapshotSource.folderName(files)).toBe("my-project");
    const source = new LocalSnapshotSource("my-project", files);
    const listing = await source.list();
    const filePaths = listing.entries
      .filter((entry) => entry.type === "file")
      .map((entry) => entry.path);

    expect(filePaths.sort()).toEqual([".env.example", "src/app.ts"]);
    expect(listing.skipped).toBe(2);
  });

  it("reads originals and keeps saved changes in memory", async () => {
    const source = new LocalSnapshotSource("my-project", files);
    expect(await source.read("src/app.ts")).toBe("export const x = 1;\n");
    await source.write("src/app.ts", "changed");
    expect(await source.read("src/app.ts")).toBe("changed");
  });
});

describe("decodeTextFile", () => {
  it("rejects binary content", async () => {
    await expect(
      decodeTextFile(new Blob([new Uint8Array([0x89, 0x50, 0x00, 0x47])]), "img.png"),
    ).rejects.toMatchObject({
      reason: "binary",
    });
  });

  it("rejects files above the editor size limit", async () => {
    const big = new Blob([new Uint8Array(MAX_EDITABLE_FILE_BYTES + 1)]);
    const error = await decodeTextFile(big, "big.log").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(SourceError);
    expect((error as SourceError).reason).toBe("too-large");
  });

  it("decodes UTF-8 text", async () => {
    expect(await decodeTextFile(new Blob(["héllo ✓"]), "a.txt")).toBe("héllo ✓");
  });
});
