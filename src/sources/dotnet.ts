/** .NET: CycloneDX BOM per project for dependencies, msbuild for the target framework, global.json for the SDK. */

import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { basename, dirname, join } from "node:path";
import { XMLParser } from "fast-xml-parser";
import { directDependencies } from "../cyclonedx.js";
import { emptyResult, finding, type DetectResult } from "../models.js";
import type { ScanContext, Source } from "../scan.js";
import { describeFailure, findTool } from "../tools.js";
import { readText, rel } from "../util.js";
import { normalise } from "../versions.js";

export const CYCLONEDX_DOTNET_VERSION = "6.3.1";
const PROJECT_SUFFIXES = [".csproj", ".fsproj", ".vbproj"];
const NO_TARGET = "couldn't read the .NET target framework";
const TFM_PROPERTIES = ["TargetFramework", "TargetFrameworks", "TargetFrameworkVersion"] as const;

type Json = Record<string, unknown>;

function isObject(value: unknown): value is Json {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** '.NET' / '.NET Framework' and the version for a target framework moniker, or null when not recognised. */
export function parseTfm(tfm: string): [".NET" | ".NET Framework", string] | null {
  const t = tfm.trim().toLowerCase().split("-")[0]!;
  let m = /^netcoreapp(\d+\.\d+)$/.exec(t);
  if (m) return [".NET", m[1]!];
  m = /^net(\d+)\.(\d+)$/.exec(t);
  if (m && Number(m[1]) >= 5) return [".NET", `${m[1]}.${m[2]}`];
  m = /^net(\d)(\d)(\d)?$/.exec(t);
  if (m) return [".NET Framework", [m[1], m[2], m[3]].filter((g) => g !== undefined).join(".")];
  m = /^v(\d+(?:\.\d+)+)$/.exec(t);
  if (m) return [".NET Framework", m[1]!];
  return null;
}

// Every element is parsed as an array, so one and many children look the same.
const parser = new XMLParser({
  removeNSPrefix: true,
  ignoreAttributes: true,
  parseTagValue: false,
  isArray: () => true,
});

function kids(el: unknown, name: string): unknown[] {
  const v = isObject(el) ? el[name] : undefined;
  return Array.isArray(v) ? v : [];
}

/** The target framework properties set in the project file's own PropertyGroups; later ones win. */
async function fileProperties(project: string): Promise<Record<string, string>> {
  const out: Record<string, string> = {};
  let doc: unknown;
  try {
    doc = parser.parse(await readText(project));
  } catch {
    return out;
  }
  for (const root of kids(doc, "Project")) {
    for (const group of kids(root, "PropertyGroup")) {
      for (const name of TFM_PROPERTIES) {
        const v = kids(group, name)[0];
        if (typeof v === "string" && v.trim()) out[name] = v.trim();
      }
    }
  }
  return out;
}

/** The properties as msbuild evaluates them, or null when msbuild is unavailable or its output is unusable. */
async function msbuildProperties(
  dotnet: string | null, project: string, ctx: ScanContext,
): Promise<Record<string, string> | null> {
  if (dotnet === null) return null;
  const r = await ctx.run(
    [dotnet, "msbuild", project, ...TFM_PROPERTIES.map((p) => `-getProperty:${p}`)],
    { cwd: dirname(project), env: ctx.env, signal: ctx.signal },
  );
  if (r.timedOut || r.code !== 0) return null;
  try {
    // dotnet may print a banner or first-run notice before the JSON.
    const start = r.stdout.search(/^\{/m);
    if (start < 0) return null;
    const data: unknown = JSON.parse(r.stdout.slice(start));
    const props = isObject(data) ? data["Properties"] : undefined;
    if (!isObject(props)) return null;
    const out: Record<string, string> = {};
    for (const name of TFM_PROPERTIES) {
      const v = props[name];
      if (typeof v === "string" && v.trim()) out[name] = v.trim();
    }
    return out;
  } catch {
    return null;
  }
}

async function targetFrameworks(
  dotnet: string | null, project: string, source: string, ctx: ScanContext, result: DetectResult,
): Promise<void> {
  const props = (await msbuildProperties(dotnet, project, ctx)) ?? (await fileProperties(project));
  const raw = props["TargetFrameworks"] ?? props["TargetFramework"] ?? props["TargetFrameworkVersion"];
  if (!raw) {
    result.unrecognised.push({ source, reason: NO_TARGET });
    return;
  }
  for (const tfm of raw.split(";").map((t) => t.trim())) {
    if (!tfm || tfm.toLowerCase().startsWith("netstandard")) continue;
    const parsed = parseTfm(tfm);
    if (parsed === null) result.unrecognised.push({ source, reason: NO_TARGET });
    else result.findings.push(finding(parsed[0], parsed[1], tfm, source));
  }
}

async function globalJson(path: string, source: string, result: DetectResult): Promise<void> {
  let sdk: unknown;
  try {
    const data: unknown = JSON.parse(await readText(path));
    const section = isObject(data) ? data["sdk"] : undefined;
    sdk = isObject(section) ? section["version"] : undefined;
  } catch {
    result.unrecognised.push({ source, reason: "couldn't parse global.json" });
    return;
  }
  if (typeof sdk !== "string") return;
  const version = normalise(sdk);
  if (version === null) result.unrecognised.push({ source, reason: "couldn't read the .NET SDK version" });
  else result.findings.push(finding(".NET", version, `SDK ${sdk}`, source));
}

export const dotnetSource: Source = {
  name: "dotnet",
  async scan(files: string[], ctx: ScanContext): Promise<DetectResult> {
    const result = emptyResult();
    for (const file of files) {
      if (basename(file) === "global.json") await globalJson(file, rel(ctx.root, file), result);
    }
    const projects = files.filter((f) => PROJECT_SUFFIXES.some((s) => f.endsWith(s)));
    if (projects.length === 0) return result;

    const dotnet = await findTool("dotnet", ctx.env);
    const hasDotnet = dotnet !== null;
    const tool = hasDotnet ? await findTool("dotnet-CycloneDX", ctx.env) : null;
    const hasTool = tool !== null;
    if (hasDotnet && !hasTool) {
      ctx.hint(`Install the CycloneDX .NET tool: dotnet tool install --global CycloneDX --version ${CYCLONEDX_DOTNET_VERSION}`);
    }

    // Created lazily so scans that never run the tool leave nothing behind.
    let tmp: string | undefined;
    let runs = 0;
    try {
      for (const project of projects) {
        const source = rel(ctx.root, project);
        await targetFrameworks(dotnet, project, source, ctx, result);

        if (!hasDotnet) {
          result.unrecognised.push({ source, reason: "not scanned (dotnet not found)" });
          continue;
        }
        if (!hasTool) {
          result.unrecognised.push({ source, reason: "not scanned (CycloneDX .NET tool not found)" });
          continue;
        }
        tmp ??= await mkdtemp(join(tmpdir(), "eolchecker-dotnet-"));
        const name = `bom-${++runs}.json`;
        ctx.progress(`Running CycloneDX .NET tool on ${source}…`);
        const r = await ctx.run(
          [tool, project, "--output-format", "Json", "--output", tmp, "--filename", name],
          { cwd: dirname(project), env: ctx.env, signal: ctx.signal },
        );
        if (r.timedOut || r.code !== 0) {
          result.unrecognised.push({ source, reason: describeFailure("CycloneDX .NET tool", r) });
          continue;
        }
        let bom: unknown;
        try {
          bom = JSON.parse(await readText(join(tmp, name)));
        } catch {
          result.unrecognised.push({ source, reason: "not scanned (CycloneDX .NET tool failed: no SBOM produced)" });
          continue;
        }
        result.dependencies.push(...directDependencies(bom, source));
      }
    } finally {
      if (tmp !== undefined) await rm(tmp, { recursive: true, force: true });
    }
    return result;
  },
};
