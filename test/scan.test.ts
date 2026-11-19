import { mkdir, mkdtemp, realpath, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { emptyResult, finding } from "../src/models.js";
import { detect, listFiles, type ScanContext, type Source } from "../src/scan.js";

let tmp: string;
beforeEach(async () => { tmp = await realpath(await mkdtemp(join(tmpdir(), "scan-"))); });
afterEach(async () => { await rm(tmp, { recursive: true, force: true }); });

async function touch(path: string): Promise<void> {
  await mkdir(dirname(path), { recursive: true });
  await writeFile(path, "");
}

function context(): ScanContext {
  return {
    root: tmp,
    env: { PATH: "" },
    run: async () => { throw new Error("no subprocess in this test"); },
    progress: () => {},
    hint: () => {},
  };
}

describe("scan", () => {
  it("skips node_modules and target", async () => {
    for (const p of ["a.txt", "node_modules/x/package.json", "target/y", "sub/b.txt", "sub/target/z", "sub/.git/HEAD"]) {
      await touch(join(tmp, p));
    }
    expect(await listFiles(tmp)).toEqual([join(tmp, "a.txt"), join(tmp, "sub", "b.txt")]);
  });

  it("reports a throwing source without stopping others", async () => {
    await touch(join(tmp, "pom.xml"));
    const seen: string[][] = [];
    const boom: Source = { name: "Boom", scan: async () => { throw new Error("bad"); } };
    const ok: Source = {
      name: "Ok",
      scan: async (files) => {
        seen.push(files);
        const r = emptyResult();
        r.findings.push(finding("Java", "17", "17", "pom.xml"));
        r.unrecognised.push({ source: "pom.xml", reason: "x" }, { source: "pom.xml", reason: "x" });
        return r;
      },
    };
    const result = await detect(tmp, context(), [boom, ok]);
    expect(seen).toEqual([[join(tmp, "pom.xml")]]);
    expect(result.findings).toEqual([finding("Java", "17", "17", "pom.xml")]);
    expect(result.unrecognised).toEqual([
      { source: ".", reason: "couldn't scan with Boom" },
      { source: "pom.xml", reason: "x" },
    ]);
  });
});
