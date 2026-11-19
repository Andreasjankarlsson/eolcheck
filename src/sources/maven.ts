/** Maven: CycloneDX BOM per module for dependencies, the effective pom for Java. */

import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { basename, dirname, join, sep } from "node:path";
import { XMLParser } from "fast-xml-parser";
import { directDependencies } from "../cyclonedx.js";
import { emptyResult, finding, type DetectResult } from "../models.js";
import type { ScanContext, Source } from "../scan.js";
import { describeFailure, findMaven, type RunResult } from "../tools.js";
import { readText, rel } from "../util.js";
import { normalise } from "../versions.js";

export const CYCLONEDX_MAVEN_PLUGIN = "org.cyclonedx:cyclonedx-maven-plugin:2.9.1";
const BOM_NAME = "eolchecker-bom";
const JAVA_PROPS = ["maven.compiler.release", "maven.compiler.source", "java.version"];

type Json = Record<string, unknown>;

/** '1.8' -> '8', '17' -> '17', '21.0.1' -> '21'. */
export function javaVersion(raw: string): string | null {
  if (!raw || raw.includes("${")) return null;
  const v = normalise(raw);
  if (v === null) return null;
  const parts = v.split(".");
  return parts[0] === "1" && parts.length > 1 ? parts[1]! : parts[0]!;
}

function isObject(value: unknown): value is Json {
  return typeof value === "object" && value !== null && !Array.isArray(value);
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

function text(el: unknown, name: string): string | null {
  const v = kids(el, name)[0];
  return typeof v === "string" && v.trim() ? v.trim() : null;
}

function walk(el: unknown, path: string[]): unknown[] {
  let current = [el];
  for (const name of path) current = current.flatMap((c) => kids(c, name));
  return current;
}

/** groupId:artifactId -> <project> element, from a single <project> or a <projects> wrapper. */
function effectiveProjects(xml: string): Map<string, unknown> {
  const out = new Map<string, unknown>();
  let doc: unknown;
  try {
    doc = parser.parse(xml);
  } catch {
    return out;
  }
  const projects = [...kids(doc, "project"), ...kids(kids(doc, "projects")[0], "project")];
  for (const p of projects) {
    const group = text(p, "groupId") ?? text(kids(p, "parent")[0], "groupId");
    const artifact = text(p, "artifactId");
    if (group && artifact) out.set(`${group}:${artifact}`, p);
  }
  return out;
}

function compilerSetting(project: unknown): string | null {
  for (const path of [["build", "plugins", "plugin"], ["build", "pluginManagement", "plugins", "plugin"]]) {
    for (const plugin of walk(project, path)) {
      if (text(plugin, "artifactId") !== "maven-compiler-plugin") continue;
      const config = kids(plugin, "configuration")[0];
      const value = text(config, "release") ?? text(config, "source");
      if (value) return value;
    }
  }
  return null;
}

function javaRaw(project: unknown): string | null {
  const props = kids(project, "properties")[0];
  for (const key of JAVA_PROPS) {
    const value = text(props, key);
    if (value) return value;
  }
  return compilerSetting(project);
}

/** The `type` qualifier of the BOM's root purl, e.g. 'jar' or 'pom'. */
function purlType(component: Json): string | null {
  const purl = component["purl"];
  if (typeof purl !== "string") return null;
  return new URLSearchParams(purl.split("?")[1]?.split("#")[0] ?? "").get("type");
}

function bomPath(pom: string): string {
  return join(dirname(pom), "target", `${BOM_NAME}.json`);
}

async function readBom(pom: string): Promise<Json | null> {
  try {
    const bom: unknown = JSON.parse(await readText(bomPath(pom)));
    return isObject(bom) ? bom : null;
  } catch {
    return null;
  }
}

function inTree(pom: string, dir: string): boolean {
  const d = dirname(pom);
  return d === dir || d.startsWith(dir + sep);
}

function succeeded(r: RunResult): boolean {
  return !r.timedOut && r.code === 0;
}

export const mavenSource: Source = {
  name: "Maven",
  async scan(files: string[], ctx: ScanContext): Promise<DetectResult> {
    const depth = (p: string): number => rel(ctx.root, p).split("/").length;
    const poms = files.filter((f) => basename(f) === "pom.xml").sort((a, b) => depth(a) - depth(b));
    const result = emptyResult();
    const done = new Set<string>();
    const gap = (pom: string, reason: string): void => {
      done.add(pom);
      result.unrecognised.push({ source: rel(ctx.root, pom), reason });
    };

    const tmp = await mkdtemp(join(tmpdir(), "eolchecker-maven-"));
    let runs = 0;
    /** Runs Maven on `pom`'s reactor and reads every pom in its tree that got a BOM. */
    const build = async (pom: string, maven: string[]): Promise<RunResult> => {
      const dir = dirname(pom);
      const tree = poms.filter((p) => !done.has(p) && inTree(p, dir));
      // A BOM left from an earlier run would look like this run's output.
      await Promise.all(tree.map((p) => rm(bomPath(p), { force: true })));
      const output = join(tmp, `effective-pom-${++runs}.xml`);
      ctx.progress(`Running Maven in ${rel(ctx.root, dir) || "."}…`);
      const r = await ctx.run(
        [...maven, "-B", "-q", "--fail-at-end", "-f", pom,
          `${CYCLONEDX_MAVEN_PLUGIN}:makeBom`, "-DoutputFormat=json", `-DoutputName=${BOM_NAME}`,
          "-DincludeTestScope=true", "help:effective-pom", `-Doutput=${output}`],
        { cwd: dir, env: ctx.env, signal: ctx.signal },
      );
      const projects = effectiveProjects(await readFile(output, "utf8").catch(() => ""));
      for (const p of tree) {
        const bom = await readBom(p);
        if (!bom) continue;
        done.add(p);
        read(p, bom, projects);
      }
      return r;
    };

    const read = (pom: string, bom: Json, projects: Map<string, unknown>): void => {
      const source = rel(ctx.root, pom);
      result.dependencies.push(...directDependencies(bom, source));
      const metadata = bom["metadata"];
      const component = isObject(metadata) && isObject(metadata["component"]) ? metadata["component"] : {};
      const project = projects.get(`${String(component["group"])}:${String(component["name"])}`);
      const raw = project === undefined ? null : javaRaw(project);
      const version = raw === null ? null : javaVersion(raw);
      if (raw !== null && version !== null) {
        result.findings.push(finding("Java", version, raw, source));
        return;
      }
      const packaging = project === undefined ? purlType(component) : (text(project, "packaging") ?? "jar");
      if (raw !== null || packaging !== "pom") {
        result.unrecognised.push({ source, reason: "couldn't read the Java version" });
      }
    };

    try {
      for (const pom of poms) {
        if (done.has(pom)) continue;
        const maven = await findMaven(dirname(pom), ctx.root, ctx.env);
        if (!maven) {
          gap(pom, "not scanned (Maven not found)");
          continue;
        }
        const r = await build(pom, maven);
        const left = poms.filter((p) => !done.has(p) && inTree(p, dirname(pom)));
        if (succeeded(r)) {
          // Poms outside this reactor stay pending and get their own run.
          if (!done.has(pom)) gap(pom, describeFailure("Maven", r));
        } else if (r.timedOut) {
          for (const p of left) gap(p, describeFailure("Maven", r));
        } else {
          // Rerunning the same reactor would fail the same way.
          if (!done.has(pom)) gap(pom, describeFailure("Maven", r));
          // One retry each, on its own reactor, for the modules that didn't build.
          for (const p of left) {
            if (done.has(p)) continue;
            const retry = await build(p, maven);
            if (!done.has(p)) gap(p, describeFailure("Maven", retry));
          }
        }
      }
    } finally {
      await rm(tmp, { recursive: true, force: true });
    }
    return result;
  },
};
