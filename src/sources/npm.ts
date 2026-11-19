/** npm: CycloneDX BOM from @cyclonedx/cyclonedx-npm for dependencies, engines and version files for Node.js. */

import { access, mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { basename, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { directDependencies } from "../cyclonedx.js";
import { emptyResult, finding, type DetectResult } from "../models.js";
import type { ScanContext, Source } from "../scan.js";
import { describeFailure, findTool } from "../tools.js";
import { dirsUp, readText, rel } from "../util.js";
import { isRange, lowest, normalise } from "../versions.js";

export const CYCLONEDX_NPM_VERSION = "7.0.1";
const LOCK_FILES = ["package-lock.json", "yarn.lock", "pnpm-lock.yaml"];

type Json = Record<string, unknown>;

function isObject(value: unknown): value is Json {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

async function exists(path: string): Promise<boolean> {
  try {
    await access(path);
    return true;
  } catch {
    return false;
  }
}

/** The plugin's CLI script, from the `bin` field of its package.json. */
async function pluginBin(): Promise<string> {
  const main = fileURLToPath(import.meta.resolve("@cyclonedx/cyclonedx-npm"));
  const dir = dirname(main);
  const pkg: unknown = JSON.parse(await readFile(join(dir, "package.json"), "utf8"));
  const bin = isObject(pkg) ? pkg["bin"] : undefined;
  const entry = typeof bin === "string" ? bin : isObject(bin) ? Object.values(bin)[0] : undefined;
  if (typeof entry !== "string") throw new Error("cyclonedx-npm has no bin entry");
  return join(dir, entry);
}

/** The nearest lock file, from `start` up to the scan root. */
async function findLock(start: string, root: string): Promise<string | null> {
  for (const dir of dirsUp(start, root)) {
    for (const name of LOCK_FILES) {
      if (await exists(join(dir, name))) return join(dir, name);
    }
  }
  return null;
}

/** bom-ref of the component for the package itself, when it is a workspace member in the BOM. */
function memberRef(bom: unknown, name: string): string | undefined {
  const components = isObject(bom) && Array.isArray(bom["components"]) ? bom["components"] : [];
  for (const c of components) {
    if (!isObject(c) || typeof c["bom-ref"] !== "string") continue;
    const full = typeof c["group"] === "string" && c["group"] ? `${c["group"]}/${String(c["name"])}` : c["name"];
    if (full === name) return c["bom-ref"];
  }
  return undefined;
}

/** Node.js finding from engines.node. */
function engines(data: Json, source: string, result: DetectResult): void {
  const engine = data["engines"];
  const node = isObject(engine) ? engine["node"] : undefined;
  if (typeof node !== "string") return;
  const version = lowest(node);
  if (version === null) {
    result.unrecognised.push({ source, reason: "couldn't read the Node.js version" });
  } else {
    result.findings.push(finding("Node.js", version, isRange(node) ? node : version, source));
  }
}

/** Node.js finding from .nvmrc or .node-version. */
async function versionFile(path: string, source: string, result: DetectResult): Promise<void> {
  const first = (await readText(path)).trim().split(/\r?\n/)[0]?.trim() ?? "";
  const version = /^[vV]?\d/.test(first) ? normalise(first) : null;
  if (version === null) result.unrecognised.push({ source, reason: "couldn't read the Node.js version" });
  else result.findings.push(finding("Node.js", version, version, source));
}

/** True when the package-lock.json at `lock` lists `memberDir` (relative to the lock's folder) in `packages`. */
async function listsMember(lock: string, memberDir: string): Promise<boolean> {
  try {
    const data: unknown = JSON.parse(await readText(lock));
    const packages = isObject(data) ? data["packages"] : undefined;
    return isObject(packages) && memberDir in packages;
  } catch {
    return false;
  }
}

/** `resolveBin` is injectable so tests can make the plugin lookup fail. */
export function createNpmSource(resolveBin: () => Promise<string> = pluginBin): Source {
  return {
  name: "npm",
  async scan(files: string[], ctx: ScanContext): Promise<DetectResult> {
    const result = emptyResult();
    const manifests = files.filter((f) => basename(f) === "package.json");
    for (const file of files) {
      if ([".nvmrc", ".node-version"].includes(basename(file))) {
        await versionFile(file, rel(ctx.root, file), result);
      }
    }
    if (manifests.length === 0) return result;

    // Created lazily so scans without a package.json leave nothing behind.
    const tmp = await mkdtemp(join(tmpdir(), "eolchecker-npm-"));
    let runs = 0;
    let bin: Promise<string> | undefined;
    try {
      for (const manifest of manifests) {
        const source = rel(ctx.root, manifest);
        const dir = dirname(manifest);
        let data: Json;
        try {
          const parsed: unknown = JSON.parse(await readText(manifest));
          if (!isObject(parsed)) throw new Error("not an object");
          data = parsed;
        } catch {
          result.unrecognised.push({ source, reason: "couldn't parse package.json" });
          continue;
        }
        engines(data, source, result);

        const lock = await findLock(dir, ctx.root);
        if (lock !== null && basename(lock) !== "package-lock.json") {
          result.unrecognised.push({ source, reason: "not scanned (yarn/pnpm not supported)" });
          continue;
        }
        let base = dir;
        let hasLock = lock !== null;
        if (lock !== null && dirname(lock) !== dir) {
          // A lock higher up only covers this package when it lists it as a workspace member.
          if (await listsMember(lock, rel(dirname(lock), dir))) base = dirname(lock);
          else hasLock = false;
        }
        const installed = (await exists(join(dir, "node_modules"))) ||
          (base !== dir && (await exists(join(base, "node_modules"))));
        if (!hasLock && !installed) {
          result.unrecognised.push({ source, reason: "not scanned (no lock file)" });
          continue;
        }
        if ((await findTool("npm", ctx.env)) === null) {
          result.unrecognised.push({ source, reason: "not scanned (npm not found)" });
          continue;
        }

        // The plugin looks for the lock file in its own folder, so a workspace member
        // is scanned from the lock's folder with -w.
        const memberDir = rel(base, dir);
        let script: string;
        try {
          script = await (bin ??= resolveBin());
        } catch (err) {
          const message = err instanceof Error ? err.message : String(err);
          result.unrecognised.push({ source, reason: `not scanned (npm failed: ${message})` });
          continue;
        }
        const output = join(tmp, `bom-${++runs}.json`);
        const { NODE_ENV: _drop, ...env } = ctx.env;
        ctx.progress(`Running npm in ${rel(ctx.root, base) || "."}…`);
        const r = await ctx.run(
          [process.execPath, script, "--output-format", "JSON", "--output-file", output,
            ...(installed ? [] : ["--package-lock-only"]), ...(memberDir ? ["-w", memberDir] : [])],
          { cwd: base, env: { ...env, npm_config_omit: "" }, signal: ctx.signal },
        );
        if (r.timedOut || r.code !== 0) {
          result.unrecognised.push({ source, reason: describeFailure("npm", r) });
          continue;
        }
        let bom: unknown;
        try {
          bom = JSON.parse(await readText(output));
        } catch {
          result.unrecognised.push({ source, reason: "not scanned (npm failed: no SBOM produced)" });
          continue;
        }
        let rootRef: string | undefined;
        if (memberDir) {
          rootRef = typeof data["name"] === "string" ? memberRef(bom, data["name"]) : undefined;
          if (rootRef === undefined) {
            result.unrecognised.push({ source, reason: "not scanned (npm failed: package not in SBOM)" });
            continue;
          }
        }
        result.dependencies.push(...directDependencies(bom, source, rootRef));
      }
    } finally {
      await rm(tmp, { recursive: true, force: true });
    }
    return result;
  },
  };
}

export const npmSource: Source = createNpmSource();
