import { existsSync } from "node:fs";
import { chmod, copyFile, cp, mkdir, mkdtemp, realpath, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { finding } from "../../src/models.js";
import { listFiles, type ScanContext } from "../../src/scan.js";
import { createNpmSource, npmSource } from "../../src/sources/npm.js";
import type { Runner, RunResult } from "../../src/tools.js";

const FIXTURES = join(dirname(fileURLToPath(import.meta.url)), "..", "fixtures");
const BOMS = join(FIXTURES, "boms");

let tmp: string;
let root: string;
let bin: string;
let calls: { cmd: string[]; cwd: string; env: NodeJS.ProcessEnv }[];
let progress: string[];

beforeEach(async () => {
  tmp = await realpath(await mkdtemp(join(tmpdir(), "npm-")));
  root = join(tmp, "project");
  bin = join(tmp, "bin");
  await mkdir(root);
  await mkdir(bin);
  await writeFile(join(bin, "npm"), "#!/bin/sh\n");
  await chmod(join(bin, "npm"), 0o755);
  calls = [];
  progress = [];
});
afterEach(async () => { await rm(tmp, { recursive: true, force: true }); });

async function project(name: string): Promise<void> {
  await cp(join(FIXTURES, "projects", name), root, { recursive: true });
}

async function put(path: string, content = ""): Promise<void> {
  await mkdir(dirname(join(root, path)), { recursive: true });
  await writeFile(join(root, path), content);
}

/** Emulates the real command: writes the recorded BOM to --output-file. */
function fakeNpm(recorded: string, result: Partial<RunResult> = {}): Runner {
  return async (cmd, opts) => {
    calls.push({ cmd, cwd: opts.cwd, env: opts.env });
    const out = cmd[cmd.indexOf("--output-file") + 1]!;
    if ((result.code ?? 0) === 0 && !result.timedOut) await copyFile(join(BOMS, recorded), out);
    return { code: 0, stdout: "", stderr: "", timedOut: false, ...result };
  };
}

const never: Runner = async () => { throw new Error("must not run"); };

async function scan(run: Runner, env: NodeJS.ProcessEnv = { PATH: bin, NODE_ENV: "production" }, source = npmSource) {
  const ctx: ScanContext = { root, env, run, progress: (m) => progress.push(m), hint: () => {} };
  return source.scan(await listFiles(root), ctx);
}

describe("npm source", () => {
  it("includes dev and peer dependencies", async () => {
    await project("npm-app");
    const result = await scan(fakeNpm("npm-app.json"));
    expect(result.dependencies.map((d) => [d.name, d.version, d.source])).toEqual([
      ["is-number", "7.0.0", "package.json"],
      ["left-pad", "1.3.0", "package.json"],
      ["ms", "2.1.3", "package.json"],
    ]);
    expect(result.unrecognised).toEqual([]);
    const [call] = calls as [(typeof calls)[number]];
    expect(call.cmd).toContain("--package-lock-only");
    expect(call.cmd.slice(0, 2)[0]).toBe(process.execPath);
    expect(call.cmd[1]).toMatch(/cyclonedx-npm-cli\.js$/);
    expect(call.cmd.slice(2, 5)).toEqual(["--output-format", "JSON", "--output-file"]);
    expect(existsSync(dirname(call.cmd[5]!))).toBe(false); // temp dir removed
    expect(call.cwd).toBe(root);
    expect("NODE_ENV" in call.env).toBe(false);
    expect(call.env["npm_config_omit"]).toBe("");
    expect(call.env["PATH"]).toBe(bin);
    expect(progress).toEqual(["Running npm in .…"]);
  });

  it("uses node_modules instead of the lock file when it is installed", async () => {
    await project("npm-app");
    await put("node_modules/is-number/package.json", "{}");
    await scan(fakeNpm("npm-app.json"));
    expect(calls[0]!.cmd).not.toContain("--package-lock-only");
  });

  it("scans a workspace member using the root lock", async () => {
    await project("npm-workspace");
    const result = await scan(fakeNpm("npm-workspace-a.json"));
    // The plugin finds no lock from inside the member, so it runs at the lock and selects the member.
    expect(calls.map((c) => c.cwd)).toEqual([root, root]);
    expect(calls[0]!.cmd).not.toContain("-w"); // the workspace root itself
    expect(calls[1]!.cmd.slice(-2)).toEqual(["-w", "packages/a"]);
    const member = result.dependencies.filter((d) => d.source === "packages/a/package.json");
    expect(member.map((d) => [d.name, d.version, d.source])).toEqual([
      ["is-number", "7.0.0", "packages/a/package.json"],
      ["left-pad", "1.3.0", "packages/a/package.json"],
    ]);
    expect(result.unrecognised).toEqual([]);
  });

  it("reports a member the BOM does not contain", async () => {
    await project("npm-workspace");
    await put("packages/a/package.json", JSON.stringify({ name: "renamed" }));
    const result = await scan(fakeNpm("npm-workspace-a.json"));
    expect(result.unrecognised).toEqual([
      { source: "packages/a/package.json", reason: "not scanned (npm failed: package not in SBOM)" }]);
  });

  it("ignores a root lock that does not list the sub-app", async () => {
    await project("npm-workspace");
    await put("tools/package.json", JSON.stringify({ name: "tools", engines: { node: "20" } }));
    const result = await scan(fakeNpm("npm-workspace-a.json"));
    expect(calls.map((c) => c.cwd)).toEqual([root, root]); // the root and member a, not tools
    expect(result.unrecognised).toEqual([{ source: "tools/package.json", reason: "not scanned (no lock file)" }]);
    expect(result.findings).toEqual([finding("Node.js", "20", "20", "tools/package.json")]);
  });

  it("treats an unreadable root lock as not listing the sub-app", async () => {
    await put("package-lock.json", "{nope");
    await put("app/package.json", "{}");
    const result = await scan(never);
    expect(result.unrecognised).toEqual([{ source: "app/package.json", reason: "not scanned (no lock file)" }]);
  });

  it("runs in a sub-app with its own node_modules and no usable lock", async () => {
    await project("npm-workspace");
    await put("tools/package.json", JSON.stringify({ name: "tools" }));
    await put("tools/node_modules/x/package.json", "{}");
    await scan(fakeNpm("npm-app.json"));
    const tools = calls.find((c) => c.cwd === join(root, "tools"))!;
    expect(tools.cmd).not.toContain("--package-lock-only");
    expect(tools.cmd).not.toContain("-w");
  });

  it("treats a workspace member as installed when the lock folder has node_modules", async () => {
    await project("npm-workspace");
    await put("node_modules/is-number/package.json", "{}");
    await scan(fakeNpm("npm-workspace-a.json"));
    expect(calls).toHaveLength(2);
    for (const c of calls) expect(c.cmd).not.toContain("--package-lock-only");
  });

  it("keeps Node.js rows when the plugin cannot be resolved", async () => {
    await project("npm-app");
    await put(".nvmrc", "20\n");
    const source = createNpmSource(async () => { throw new Error("cannot find plugin"); });
    const result = await scan(never, undefined, source);
    expect(result.findings.map((f) => f.component)).toEqual(["Node.js", "Node.js"]);
    expect(result.unrecognised).toEqual([
      { source: "package.json", reason: "not scanned (npm failed: cannot find plugin)" }]);
  });

  it.each([["yarn.lock"], ["pnpm-lock.yaml"]])("reports %s as not scanned", async (lock) => {
    await put("package.json", JSON.stringify({ engines: { node: ">=18" }, dependencies: { a: "1.0.0" } }));
    await put(lock);
    const result = await scan(never);
    expect(result.unrecognised).toEqual([
      { source: "package.json", reason: "not scanned (yarn/pnpm not supported)" }]);
    expect(result.dependencies).toEqual([]);
    expect(result.findings).toEqual([finding("Node.js", "18", ">=18", "package.json")]);
  });

  it("uses the nearest lock file, npm first within a folder", async () => {
    await put("yarn.lock");
    await put("web/package-lock.json", "{}");
    await put("web/yarn.lock");
    await put("web/package.json", "{}");
    await put("api/package.json", "{}");
    const result = await scan(fakeNpm("npm-app.json"));
    expect(calls.map((c) => c.cwd)).toEqual([join(root, "web")]);
    expect(result.unrecognised).toEqual([
      { source: "api/package.json", reason: "not scanned (yarn/pnpm not supported)" }]);
  });

  it("reports a missing lock file", async () => {
    await put("package.json", JSON.stringify({ dependencies: { a: "1.0.0" } }));
    const result = await scan(never);
    expect(result.unrecognised).toEqual([{ source: "package.json", reason: "not scanned (no lock file)" }]);
  });

  it("reports npm missing", async () => {
    await project("npm-app");
    const result = await scan(never, { PATH: "" });
    expect(result.unrecognised).toEqual([{ source: "package.json", reason: "not scanned (npm not found)" }]);
    expect(result.findings).toEqual([finding("Node.js", "18", ">=18", "package.json")]);
  });

  it("reports a failure and a timeout, keeping the Node.js row", async () => {
    await project("npm-app");
    const failed = await scan(fakeNpm("npm-app.json", { code: 1, stderr: "\nERROR | boom\nmore" }));
    expect(failed.unrecognised).toEqual([
      { source: "package.json", reason: "not scanned (npm failed: ERROR | boom)" }]);
    expect(failed.findings).toHaveLength(1);
    const slow = await scan(fakeNpm("npm-app.json", { code: null, timedOut: true }));
    expect(slow.unrecognised).toEqual([{ source: "package.json", reason: "not scanned (npm timed out)" }]);
  });

  it("reports an unreadable BOM as a failure", async () => {
    await project("npm-app");
    const run: Runner = async () => ({ code: 0, stdout: "", stderr: "", timedOut: false });
    const result = await scan(run);
    expect(result.unrecognised).toEqual([
      { source: "package.json", reason: "not scanned (npm failed: no SBOM produced)" }]);
  });
});

describe("Node.js runtime", () => {
  it("reads .nvmrc", async () => {
    await put("web/.nvmrc", "v18.17.0\n");
    expect((await scan(never)).findings).toEqual([finding("Node.js", "18.17.0", "18.17.0", "web/.nvmrc")]);
  });

  it("reads .node-version", async () => {
    await put(".node-version", "20\n");
    expect((await scan(never)).findings).toEqual([finding("Node.js", "20", "20", ".node-version")]);
  });

  it("reports an lts alias as unreadable", async () => {
    await put(".nvmrc", "lts/hydrogen\n");
    expect((await scan(never)).unrecognised).toEqual([
      { source: ".nvmrc", reason: "couldn't read the Node.js version" }]);
  });

  it("reads engines.node and shows a range as written", async () => {
    await put("package.json", JSON.stringify({ engines: { node: ">=18" } }));
    await put("a/package.json", JSON.stringify({ engines: { node: "20.1.0" } }));
    await put("b/package.json", JSON.stringify({ engines: { node: "latest" } }));
    await put("c/package.json", JSON.stringify({ engines: { npm: ">=9" } }));
    const result = await scan(never);
    expect(result.findings).toEqual([
      finding("Node.js", "18", ">=18", "package.json"),
      finding("Node.js", "20.1.0", "20.1.0", "a/package.json"),
    ]);
    expect(result.unrecognised.filter((u) => u.source === "b/package.json" && u.reason.startsWith("couldn"))).toEqual([
      { source: "b/package.json", reason: "couldn't read the Node.js version" }]);
  });

  it("reports an unparseable package.json", async () => {
    await put("package.json", "{nope");
    expect((await scan(never)).unrecognised).toEqual([
      { source: "package.json", reason: "couldn't parse package.json" }]);
  });
});
