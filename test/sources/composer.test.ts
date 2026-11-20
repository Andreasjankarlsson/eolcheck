import { existsSync } from "node:fs";
import { chmod, copyFile, cp, mkdir, mkdtemp, realpath, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { finding } from "../../src/models.js";
import { listFiles, type ScanContext } from "../../src/scan.js";
import { composerSource } from "../../src/sources/composer.js";
import type { Runner, RunResult } from "../../src/tools.js";

const FIXTURES = join(dirname(fileURLToPath(import.meta.url)), "..", "fixtures");
const BOMS = join(FIXTURES, "boms");

let tmp: string;
let root: string;
let bin: string;
let calls: { cmd: string[]; cwd: string; env: NodeJS.ProcessEnv }[];
let progress: string[];
let hints: string[];

beforeEach(async () => {
  tmp = await realpath(await mkdtemp(join(tmpdir(), "composer-")));
  root = join(tmp, "project");
  bin = join(tmp, "bin");
  await mkdir(root);
  await mkdir(bin);
  calls = [];
  progress = [];
  hints = [];
});
afterEach(async () => { await rm(tmp, { recursive: true, force: true }); });

async function install(...names: string[]): Promise<void> {
  for (const name of names) {
    await writeFile(join(bin, name), "#!/bin/sh\n");
    await chmod(join(bin, name), 0o755);
  }
}

async function put(path: string, content = ""): Promise<void> {
  await mkdir(dirname(join(root, path)), { recursive: true });
  await writeFile(join(root, path), content);
}

const manifest = (data: unknown): string => JSON.stringify(data);

/**
 * Emulates composer: writes the BOM to --output-file. composer-app.json is hand-written in the
 * shape cyclonedx-php-composer 6.x produces (Composer is not installed here); Task 15's tool test
 * verifies the real plugin output.
 */
function fake(opts: { bom?: string; result?: Partial<RunResult> } = {}): Runner {
  return async (cmd, o) => {
    calls.push({ cmd, cwd: o.cwd, env: o.env });
    const r: RunResult = { code: 0, stdout: "", stderr: "", timedOut: false, ...opts.result };
    if (r.code === 0 && !r.timedOut) {
      const out = cmd.find((a) => a.startsWith("--output-file="))!.slice("--output-file=".length);
      await copyFile(join(BOMS, opts.bom ?? "composer-app.json"), out);
    }
    return r;
  };
}

const never: Runner = async () => { throw new Error("must not run"); };

async function scan(run: Runner, env: NodeJS.ProcessEnv = { PATH: bin }) {
  const ctx: ScanContext = {
    root, env, run, progress: (m) => progress.push(m), hint: (m) => hints.push(m),
  };
  return composerSource.scan(await listFiles(root), ctx);
}

describe("Composer source", () => {
  it("includes require-dev packages and only direct ones", async () => {
    await cp(join(FIXTURES, "projects", "composer-app"), root, { recursive: true });
    await install("composer");
    const result = await scan(fake());
    expect(result.dependencies.map((d) => [d.ecosystem, d.name, d.version, d.source])).toEqual([
      ["Composer", "laravel/framework", "10.48.4", "composer.json"],
      ["Composer", "phpunit/phpunit", "10.5.0", "composer.json"],
    ]);
    expect(result.findings).toEqual([finding("PHP", "8.1", "^8.1", "composer.json")]);
    expect(result.unrecognised).toEqual([]);
    const c = calls[0]!;
    expect(c.cmd.slice(0, 5)).toEqual([
      join(bin, "composer"), "--no-interaction", "--working-dir", root, "CycloneDX:make-sbom"]);
    expect(c.cmd[5]).toBe("--output-format=JSON");
    expect(c.cmd[6]).toMatch(/^--output-file=.*bom\.json$/);
    expect(c.cmd[7]).toBe("composer.json");
    expect(existsSync(c.cmd[6]!.slice("--output-file=".length))).toBe(false); // temp dir removed
    expect(c.env["PATH"]).toBe(bin);
    expect(progress).toEqual(["Running Composer in .…"]);
  });

  it("reports a missing lock file", async () => {
    await put("composer.json", manifest({ require: { "laravel/framework": "^10.0" } }));
    await install("composer");
    const result = await scan(never);
    expect(result.unrecognised).toEqual([{ source: "composer.json", reason: "not scanned (no lock file)" }]);
  });

  it("reports Composer missing", async () => {
    await put("composer.json", "{}");
    await put("composer.lock", "{}");
    const result = await scan(never);
    expect(result.unrecognised).toEqual([{ source: "composer.json", reason: "not scanned (Composer not found)" }]);
  });

  it("reports a missing plugin with one hint per run", async () => {
    await put("a/composer.json", "{}");
    await put("a/composer.lock", "{}");
    await put("b/composer.json", "{}");
    await put("b/composer.lock", "{}");
    await install("composer");
    const stderr = '\nCommand "CycloneDX:make-sbom" is not defined.\n';
    const result = await scan(fake({ result: { code: 1, stderr } }));
    expect(result.unrecognised).toEqual([
      { source: "a/composer.json", reason: "not scanned (Composer CycloneDX plugin not found)" },
      { source: "b/composer.json", reason: "not scanned (Composer CycloneDX plugin not found)" },
    ]);
    expect(hints).toEqual([
      "Install the Composer CycloneDX plugin: composer global config --no-plugins allow-plugins.cyclonedx/cyclonedx-php-composer true && composer global require cyclonedx/cyclonedx-php-composer:6.2.0",
    ]);
  });

  it("reports another failure and still scans the next manifest", async () => {
    await put("a/composer.json", "{}");
    await put("a/composer.lock", "{}");
    await put("b/composer.json", "{}");
    await put("b/composer.lock", "{}");
    await install("composer");
    const base = fake();
    let n = 0;
    const run: Runner = async (cmd, o) =>
      ++n === 1 ? { code: 1, stdout: "", stderr: "\nboom\n", timedOut: false } : base(cmd, o);
    const result = await scan(run);
    expect(result.unrecognised).toEqual([{ source: "a/composer.json", reason: "not scanned (Composer failed: boom)" }]);
    expect(result.dependencies.map((d) => d.source)).toEqual(["b/composer.json", "b/composer.json"]);
    expect(hints).toEqual([]);
  });

  it("reports a timeout", async () => {
    await put("composer.json", "{}");
    await put("composer.lock", "{}");
    await install("composer");
    const result = await scan(fake({ result: { code: null, timedOut: true } }));
    expect(result.unrecognised).toEqual([{ source: "composer.json", reason: "not scanned (Composer timed out)" }]);
  });

  it("reports a run that produced no SBOM", async () => {
    await put("composer.json", "{}");
    await put("composer.lock", "{}");
    await install("composer");
    const run: Runner = async () => ({ code: 0, stdout: "", stderr: "", timedOut: false });
    const result = await scan(run);
    expect(result.unrecognised).toEqual([
      { source: "composer.json", reason: "not scanned (Composer failed: no SBOM produced)" }]);
  });

  it("reads a PHP range from require", async () => {
    await put("composer.json", manifest({ require: { php: ">=7.4" } }));
    const result = await scan(never);
    expect(result.findings).toEqual([finding("PHP", "7.4", ">=7.4", "composer.json")]);
  });

  it("prefers config.platform.php", async () => {
    await put("composer.json", manifest({ require: { php: "^8.1" }, config: { platform: { php: "8.2.10" } } }));
    const result = await scan(never);
    expect(result.findings).toEqual([finding("PHP", "8.2.10", "8.2.10", "composer.json")]);
  });

  it("reports an unreadable PHP version", async () => {
    await put("composer.json", manifest({ require: { php: "dev-master" } }));
    const result = await scan(never);
    expect(result.findings).toEqual([]);
    expect(result.unrecognised[0]).toEqual({ source: "composer.json", reason: "couldn't read the PHP version" });
  });

  it("reports a broken composer.json", async () => {
    await put("composer.json", "{");
    const result = await scan(never);
    expect(result.unrecognised).toEqual([{ source: "composer.json", reason: "couldn't parse composer.json" }]);
  });
});
