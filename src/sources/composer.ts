/** Composer: CycloneDX BOM per composer.json for dependencies, composer.json itself for the PHP runtime. */

import { mkdir, mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { basename, dirname, join } from "node:path";
import { directDependencies } from "../cyclonedx.js";
import { emptyResult, finding, type DetectResult } from "../models.js";
import type { ScanContext, Source } from "../scan.js";
import { describeFailure, findTool } from "../tools.js";
import { readText, rel } from "../util.js";
import { isRange, lowest } from "../versions.js";

export const CYCLONEDX_COMPOSER_VERSION = "6.2.0";

type Json = Record<string, unknown>;

function isObject(value: unknown): value is Json {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** PHP finding from config.platform.php, else require.php. */
function phpRuntime(data: Json, source: string, result: DetectResult): void {
  const config = data["config"];
  const platform = isObject(config) && isObject(config["platform"]) ? config["platform"]["php"] : undefined;
  const require = data["require"];
  const php = typeof platform === "string" ? platform : isObject(require) ? require["php"] : undefined;
  if (typeof php !== "string") return;
  const version = lowest(php);
  if (version === null) {
    result.unrecognised.push({ source, reason: "couldn't read the PHP version" });
  } else {
    result.findings.push(finding("PHP", version, isRange(php) ? php : version, source));
  }
}

async function exists(path: string): Promise<boolean> {
  try {
    await readText(path);
    return true;
  } catch {
    return false;
  }
}

export const composerSource: Source = {
  name: "composer",
  async scan(files: string[], ctx: ScanContext): Promise<DetectResult> {
    const result = emptyResult();
    const manifests = files.filter((f) => basename(f) === "composer.json");
    if (manifests.length === 0) return result;

    const composer = await findTool("composer", ctx.env);
    // Created lazily so scans that never run Composer leave nothing behind.
    let tmp: string | undefined;
    let runs = 0;
    let hinted = false;
    try {
      for (const manifest of manifests) {
        const source = rel(ctx.root, manifest);
        const dir = dirname(manifest);
        let data: unknown;
        try {
          data = JSON.parse(await readText(manifest));
        } catch {
          data = undefined;
        }
        if (!isObject(data)) {
          result.unrecognised.push({ source, reason: "couldn't parse composer.json" });
          continue;
        }
        phpRuntime(data, source, result);

        if (!(await exists(join(dir, "composer.lock")))) {
          result.unrecognised.push({ source, reason: "not scanned (no lock file)" });
          continue;
        }
        if (composer === null) {
          result.unrecognised.push({ source, reason: "not scanned (Composer not found)" });
          continue;
        }

        tmp ??= await mkdtemp(join(tmpdir(), "eolchecker-composer-"));
        const outDir = join(tmp, `run-${++runs}`);
        await mkdir(outDir);
        const output = join(outDir, "bom.json");
        ctx.progress(`Running Composer in ${rel(ctx.root, dir) || "."}…`);
        const r = await ctx.run(
          [composer, "--no-interaction", "--working-dir", dir, "CycloneDX:make-sbom",
            "--output-format=JSON", `--output-file=${output}`, "composer.json"],
          { cwd: dir, env: ctx.env, signal: ctx.signal },
        );
        if (r.timedOut || r.code !== 0) {
          if (!r.timedOut && r.stderr.includes("is not defined")) {
            result.unrecognised.push({ source, reason: "not scanned (Composer CycloneDX plugin not found)" });
            if (!hinted) {
              hinted = true;
              ctx.hint(
                "Install the Composer CycloneDX plugin: composer global config --no-plugins " +
                "allow-plugins.cyclonedx/cyclonedx-php-composer true && composer global require " +
                `cyclonedx/cyclonedx-php-composer:${CYCLONEDX_COMPOSER_VERSION}`);
            }
          } else {
            result.unrecognised.push({ source, reason: describeFailure("Composer", r) });
          }
          continue;
        }
        let bom: unknown;
        try {
          bom = JSON.parse(await readText(output));
        } catch {
          result.unrecognised.push({ source, reason: "not scanned (Composer failed: no SBOM produced)" });
          continue;
        }
        result.dependencies.push(...directDependencies(bom, source).filter((d) => d.name.includes("/")));
      }
    } finally {
      if (tmp !== undefined) await rm(tmp, { recursive: true, force: true });
    }
    return result;
  },
};
