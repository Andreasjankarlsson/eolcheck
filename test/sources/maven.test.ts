import { existsSync } from "node:fs";
import { chmod, copyFile, cp, mkdir, mkdtemp, realpath, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { finding } from "../../src/models.js";
import { listFiles, type ScanContext } from "../../src/scan.js";
import { javaVersion, mavenSource } from "../../src/sources/maven.js";
import type { RunResult, Runner } from "../../src/tools.js";

const FIXTURES = join(dirname(fileURLToPath(import.meta.url)), "..", "fixtures");
const BOMS = join(FIXTURES, "boms");

/** Module folder (relative to the project) -> recorded BOM. */
const RECORDED: Record<string, string> = {
  "": "maven-multi-root.json",
  app: "maven-multi-app.json",
  lib: "maven-multi-lib.json",
};

interface Outcome { modules: string[]; effective?: boolean; result?: Partial<RunResult> }

let tmp: string;
let root: string;
let bin: string;
let calls: { cmd: string[]; cwd: string }[];
let progress: string[];

beforeEach(async () => {
  tmp = await realpath(await mkdtemp(join(tmpdir(), "maven-")));
  root = join(tmp, "project");
  bin = join(tmp, "bin");
  await cp(join(FIXTURES, "projects", "maven-multi"), root, { recursive: true });
  await mkdir(bin);
  await writeFile(join(bin, "mvn"), "#!/bin/sh\n");
  await chmod(join(bin, "mvn"), 0o755);
  calls = [];
  progress = [];
});
afterEach(async () => { await rm(tmp, { recursive: true, force: true }); });

/** Emulates the real command: writes each module's BOM to target/ and the effective pom to -Doutput. */
function fakeMaven(plan: (pom: string) => Outcome): Runner {
  return async (cmd, opts) => {
    calls.push({ cmd, cwd: opts.cwd });
    const pom = cmd[cmd.indexOf("-f") + 1]!;
    const outcome = plan(pom.slice(root.length + 1));
    for (const m of outcome.modules) {
      const target = join(root, m, "target");
      await mkdir(target, { recursive: true });
      await copyFile(join(BOMS, RECORDED[m]!), join(target, "eolchecker-bom.json"));
    }
    const output = cmd.find((a) => a.startsWith("-Doutput="))!.slice("-Doutput=".length);
    if (outcome.effective !== false) await copyFile(join(BOMS, "maven-multi-effective-pom.xml"), output);
    return { code: 0, stdout: "", stderr: "", timedOut: false, ...outcome.result };
  };
}

const allModules = (): Outcome => ({ modules: ["", "app", "lib"] });

function context(run: Runner, env: NodeJS.ProcessEnv = { PATH: bin }): ScanContext {
  return { root, env, run, progress: (m) => progress.push(m), hint: () => {} };
}

async function scan(run: Runner, env?: NodeJS.ProcessEnv) {
  return mavenSource.scan(await listFiles(root), context(run, env));
}

describe("javaVersion", () => {
  it.each([["1.8", "8"], ["17", "17"], ["21.0.1", "21"], ["${x}", null]])("%s -> %s", (raw, expected) => {
    expect(javaVersion(raw)).toBe(expected);
  });
});

describe("maven source", () => {
  it("reads direct Maven dependencies per module", async () => {
    const result = await scan(fakeMaven(allModules));
    expect(result.dependencies.map((d) => [d.name, d.version, d.source])).toEqual([
      ["org.springframework.boot:spring-boot-starter-web", "3.3.5", "app/pom.xml"],
      ["junit:junit", "4.13.2", "app/pom.xml"],
    ]);
    expect(result.unrecognised).toEqual([]);
    expect(calls.map((c) => c.cwd)).toEqual([root]);
    expect(progress).toEqual(["Running Maven in .…"]);
  });

  it("reads Java from the effective pom", async () => {
    const result = await scan(fakeMaven(allModules));
    expect(result.findings).toEqual([finding("Java", "17", "17", "app/pom.xml")]);
    expect(result.unrecognised.filter((u) => u.source === "lib/pom.xml")).toEqual([]);
  });

  it("passes the pinned plugin and test scope", async () => {
    await scan(fakeMaven(allModules));
    const [{ cmd }] = calls as [{ cmd: string[] }];
    expect(cmd.slice(0, 5)).toEqual([join(bin, "mvn"), "-B", "-q", "--fail-at-end", "-f"]);
    expect(cmd[5]).toBe(join(root, "pom.xml"));
    expect(cmd).toContain("org.cyclonedx:cyclonedx-maven-plugin:2.9.1:makeBom");
    expect(cmd).toContain("-DincludeTestScope=true");
    expect(cmd).toContain("-DoutputName=eolchecker-bom");
    expect(cmd).toContain("help:effective-pom");
    const output = cmd.find((a) => a.startsWith("-Doutput="))!.slice("-Doutput=".length);
    expect(existsSync(dirname(output))).toBe(false); // temp dir removed
  });

  it("reports Maven missing", async () => {
    const result = await scan(fakeMaven(allModules), { PATH: "" });
    expect(calls).toEqual([]);
    expect(result.unrecognised).toEqual(["pom.xml", "app/pom.xml", "lib/pom.xml"].map((source) => (
      { source, reason: "not scanned (Maven not found)" })));
  });

  it("keeps the modules that built when one fails", async () => {
    // A BOM left over from an earlier run must not count as built.
    await mkdir(join(root, "lib", "target"), { recursive: true });
    await copyFile(join(BOMS, "maven-multi-lib.json"), join(root, "lib", "target", "eolchecker-bom.json"));
    const failed = { code: 1, stderr: "\n[ERROR] Could not resolve dependencies\n[ERROR] more" };
    const result = await scan(fakeMaven((pom) => (
      pom === "pom.xml" ? { modules: ["", "app"], result: failed } : { modules: [], effective: false, result: failed })));
    expect(calls.map((c) => c.cmd[5])).toEqual([join(root, "pom.xml"), join(root, "lib", "pom.xml")]);
    expect(calls[1]!.cwd).toBe(join(root, "lib"));
    expect(result.dependencies.map((d) => d.source)).toEqual(["app/pom.xml", "app/pom.xml"]);
    expect(result.findings).toEqual([finding("Java", "17", "17", "app/pom.xml")]);
    expect(result.unrecognised).toEqual([
      { source: "lib/pom.xml", reason: "not scanned (Maven failed: [ERROR] Could not resolve dependencies)" },
    ]);
  });

  it("reports a timeout", async () => {
    const result = await scan(fakeMaven(() => (
      { modules: [], effective: false, result: { code: null, timedOut: true } })));
    expect(calls).toHaveLength(1);
    expect(result.unrecognised).toEqual(["pom.xml", "app/pom.xml", "lib/pom.xml"].map((source) => (
      { source, reason: "not scanned (Maven timed out)" })));
  });

  it("reports a jar module without Java", async () => {
    const result = await scan(fakeMaven(() => ({ modules: ["", "app", "lib"], effective: false })));
    expect(result.findings).toEqual([]);
    expect(result.unrecognised).toEqual([{ source: "app/pom.xml", reason: "couldn't read the Java version" }]);
  });
});
