import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { dirsUp, readText, rel } from "../src/util.js";

describe("util", () => {
  it("dirsUp walks from start to root inclusive", () => {
    expect(dirsUp("/r/a/b", "/r")).toEqual(["/r/a/b", "/r/a", "/r"]);
  });

  it("dirsUp stops at start when it is outside root", () => {
    expect(dirsUp("/x", "/r")).toEqual(["/x"]);
  });

  it("readText strips a UTF-8 BOM", async () => {
    const dir = await mkdtemp(join(tmpdir(), "eol-"));
    try {
      const file = join(dir, "a.json");
      await writeFile(file, "﻿{}");
      expect(await readText(file)).toBe("{}");
    } finally {
      await rm(dir, { recursive: true, force: true });
    }
  });

  it("rel returns a POSIX relative path", () => {
    expect(rel("/r", "/r/a/b.txt")).toBe("a/b.txt");
  });
});
