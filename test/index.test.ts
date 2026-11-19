import { chmod, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiUnavailable, renderTable, scan, writeSbom } from "../src/index.js";
import type { Runner } from "../src/tools.js";
import { FULL, catalogue } from "./fixtures/catalogue.js";

let root: string;
let cacheDir: string;

beforeEach(async () => {
  root = await mkdtemp(join(tmpdir(), "index-root-"));
  cacheDir = await mkdtemp(join(tmpdir(), "index-cache-"));
});
afterEach(async () => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  await rm(root, { recursive: true, force: true });
  await rm(cacheDir, { recursive: true, force: true });
});

const fakeFetch = (async () => new Response(JSON.stringify(FULL), { status: 200 })) as typeof fetch;

async function fakeMaven(): Promise<void> {
  await writeFile(join(root, "pom.xml"), "<project/>");
  await writeFile(join(root, "mvnw"), "#!/bin/sh\n");
  await chmod(join(root, "mvnw"), 0o755);
}

describe("scan", () => {
  it("returns an empty report without touching the catalogue for an empty folder", async () => {
    const factory = vi.fn(async () => catalogue());
    const report = await scan(root, { catalogue: factory });
    expect(factory).not.toHaveBeenCalled();
    expect(report).toEqual({ rows: [], sbom: [], unrecognised: [], hints: [] });
  });

  it("uses the cacheDir option", async () => {
    await writeFile(join(root, "Dockerfile"), "FROM node:18\n");
    vi.stubGlobal("fetch", fakeFetch);
    await scan(root, { cacheDir });
    expect(JSON.parse(await readFile(join(cacheDir, "products-full.json"), "utf8"))).toEqual(FULL);
  });

  it("never writes to stdout or stderr", async () => {
    await writeFile(join(root, "Dockerfile"), "FROM node:18\n");
    const out = vi.spyOn(process.stdout, "write");
    const err = vi.spyOn(process.stderr, "write");
    const report = await scan(root, { catalogue: async () => catalogue() });
    expect(report.rows.length).toBeGreaterThan(0);
    expect(out).not.toHaveBeenCalled();
    expect(err).not.toHaveBeenCalled();
  });

  it("forwards progress messages", async () => {
    await fakeMaven();
    const runner: Runner = async () => ({ code: 1, stdout: "", stderr: "boom", timedOut: false });
    const messages: string[] = [];
    const report = await scan(root, {
      runner, catalogue: async () => catalogue(), onProgress: (m) => messages.push(m),
    });
    expect(messages).toEqual(["Running Maven in .…"]);
    expect(report.unrecognised.length).toBe(1);
  });

  it("passes options.env to the runner", async () => {
    await fakeMaven();
    const env = { PATH: "/nowhere", MARKER: "yes" };
    const seen: unknown[] = [];
    const runner: Runner = async (_cmd, opts) => {
      seen.push(opts.env);
      return { code: 1, stdout: "", stderr: "boom", timedOut: false };
    };
    await scan(root, { runner, env, catalogue: async () => catalogue() });
    expect(seen).toEqual([env]);
  });

  it("lets ApiUnavailable propagate", async () => {
    await writeFile(join(root, "Dockerfile"), "FROM node:18\n");
    await expect(
      scan(root, { catalogue: async () => { throw new ApiUnavailable("down"); } }),
    ).rejects.toBeInstanceOf(ApiUnavailable);
  });

  it("re-exports the output helpers", () => {
    expect(typeof writeSbom).toBe("function");
    expect(typeof renderTable).toBe("function");
  });
});
