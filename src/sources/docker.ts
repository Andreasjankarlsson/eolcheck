/** Docker: base images from Dockerfiles and compose files. */

import { basename } from "node:path";
import { parse } from "yaml";
import { emptyResult, type DetectResult, type Dependency } from "../models.js";
import type { ScanContext, Source } from "../scan.js";
import { readText, rel } from "../util.js";
import { normalise } from "../versions.js";

const COMPOSE = /^(docker-)?compose.*\.ya?ml$/;
const VAR = /\$\{(\w+)(?:(:?-)([^}]*))?\}|\$(\w+)/g;
const LEADING_VERSION = /^[vV]?(\d+(?:\.\d+)*)/;

const NO_PIN = "image tag doesn't pin a version";
const DIGEST_ONLY = "image pinned by digest only";
const BUILD_VARIABLE = "image tag set by a build variable";
const COMPOSE_VARIABLE = "image tag set by a variable";

function appliesTo(path: string): boolean {
  const name = basename(path);
  return name === "Dockerfile" || name.startsWith("Dockerfile.") ||
    name.toLowerCase().endsWith(".dockerfile") || COMPOSE.test(name);
}

/** 'host:5000/app:1.2@sha256:x' -> ['host:5000/app', '1.2', 'sha256:x']. */
export function splitImage(ref: string): [string, string | null, string | null] {
  const at = ref.indexOf("@");
  let name = at === -1 ? ref : ref.slice(0, at);
  const digest = at === -1 ? "" : ref.slice(at + 1);
  let tag = "";
  if (name.slice(name.lastIndexOf("/") + 1).includes(":")) {
    const colon = name.lastIndexOf(":");
    tag = name.slice(colon + 1);
    name = name.slice(0, colon);
  }
  return [name, tag || null, digest || null];
}

/** Replaces $VAR / ${VAR} / ${VAR:-d} / ${VAR-d}; unknown variables stay as written. */
function substitute(text: string, variables: Map<string, string>): string {
  return text.replace(VAR, (whole, braced?: string, op?: string, fallback?: string, bare?: string) => {
    const name = (braced || bare)!;
    const value = variables.get(name);
    if (value !== undefined && !(op === ":-" && value === "")) return value;
    if (op !== undefined) return fallback!;
    return whole;
  });
}

/** Undefined when the image name still contains a variable. */
function dependency(ref: string, source: string, variableReason: string = BUILD_VARIABLE): Dependency | undefined {
  const [name, tag, digest] = splitImage(ref);
  if (!name || name.includes("$")) return undefined;
  const match = tag ? LEADING_VERSION.exec(tag) : null;
  const version = match ? normalise(match[0]) : null;
  const dep: Dependency = {
    ecosystem: "Docker",
    name,
    version,
    display: tag || digest || "latest",
    source,
  };
  if (tag) dep.tag = tag;
  if (version === null) {
    if (tag && tag.includes("$")) dep.missing = variableReason;
    else if (tag === null && digest) dep.missing = DIGEST_ONLY;
    else dep.missing = NO_PIN;
  }
  return dep;
}

function logicalLines(text: string): string[] {
  const lines: string[] = [];
  let buffer = "";
  for (const raw of text.split(/\r\n|[\n\r\v\f\x1c-\x1e\x85\u2028\u2029]/)) {
    const stripped = raw.trim();
    if (stripped.startsWith("#")) continue;
    if (stripped.endsWith("\\")) {
      buffer += stripped.slice(0, -1) + " ";
      continue;
    }
    lines.push((buffer + stripped).trim());
    buffer = "";
  }
  if (buffer.trim()) lines.push(buffer.trim());
  return lines;
}

async function scanDockerfile(path: string, root: string, result: DetectResult): Promise<void> {
  const source = rel(root, path);
  const variables = new Map<string, string>();
  const aliases = new Set<string>();
  for (const line of logicalLines(await readText(path))) {
    const parts = line.split(/\s+/).filter((p) => p !== "");
    if (parts.length === 0) continue;
    const keyword = parts[0]!.toUpperCase();
    if (keyword === "ARG") {
      for (const token of parts.slice(1)) {
        const eq = token.indexOf("=");
        if (eq === -1) continue;
        const key = token.slice(0, eq);
        if (!variables.has(key)) variables.set(key, token.slice(eq + 1).replace(/^["']+|["']+$/g, ""));
      }
    } else if (keyword === "FROM") {
      const args = parts.slice(1).filter((p) => !p.startsWith("--"));
      if (args.length === 0) continue;
      const ref = substitute(args[0]!, variables);
      const aliasAfter = args.length >= 3 && args[1]!.toUpperCase() === "AS" ? args[2]!.toLowerCase() : null;
      const skip = ref.toLowerCase() === "scratch" || aliases.has(ref.toLowerCase());
      if (aliasAfter) aliases.add(aliasAfter);
      if (skip) continue;
      const dep = dependency(ref, source);
      if (dep === undefined) {
        result.unrecognised.push({ source, reason: `couldn't read the image name in FROM ${args[0]}` });
      } else {
        result.dependencies.push(dep);
      }
    }
  }
}

async function scanCompose(path: string, root: string, result: DetectResult): Promise<void> {
  const source = rel(root, path);
  const parseError = () => result.unrecognised.push({ source, reason: `couldn't parse ${basename(path)}` });
  let data: unknown;
  try {
    data = parse(await readText(path));
  } catch {
    parseError();
    return;
  }
  if (data === null || data === undefined) return;
  if (typeof data !== "object" || Array.isArray(data)) {
    parseError();
    return;
  }
  const services = (data as Record<string, unknown>)["services"];
  if (typeof services !== "object" || services === null || Array.isArray(services)) return;
  for (const service of Object.values(services)) {
    const image = typeof service === "object" && service !== null && !Array.isArray(service)
      ? (service as Record<string, unknown>)["image"] : undefined;
    if (typeof image !== "string") continue;
    const dep = dependency(substitute(image.trim(), new Map()), source, COMPOSE_VARIABLE);
    if (dep === undefined) {
      result.unrecognised.push({ source, reason: `couldn't read the image name in image: ${image}` });
    } else {
      result.dependencies.push(dep);
    }
  }
}

export const dockerSource: Source = {
  name: "docker",
  async scan(files: string[], ctx: ScanContext): Promise<DetectResult> {
    const result = emptyResult();
    for (const file of files.filter(appliesTo)) {
      if (COMPOSE.test(basename(file))) await scanCompose(file, ctx.root, result);
      else await scanDockerfile(file, ctx.root, result);
    }
    return result;
  },
};
