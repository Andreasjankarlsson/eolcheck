/** Reads direct dependencies out of a CycloneDX JSON SBOM. */

import type { Dependency, Ecosystem } from "./models.js";
import { normalise } from "./versions.js";

type Json = Record<string, unknown>;

function isObject(value: unknown): value is Json {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function decode(segment: string): string {
  try {
    return decodeURIComponent(segment);
  } catch {
    return segment;
  }
}

/** 'pkg:npm/%40a/b@1?x=y#z' -> ecosystem and name, or null when unsupported. */
function fromPurl(purl: string): { ecosystem: Ecosystem; name: string } | null {
  if (!purl.startsWith("pkg:")) return null;
  let rest = purl.slice(4).split("#")[0]!.split("?")[0]!;
  const slash = rest.indexOf("/");
  if (slash < 0) return null;
  const type = rest.slice(0, slash).toLowerCase();
  rest = rest.slice(slash + 1);
  const at = rest.lastIndexOf("@");
  if (at > 0) rest = rest.slice(0, at);
  const parts = rest.split("/").map(decode);
  if (parts.some((p) => p === "")) return null;
  switch (type) {
    case "npm":
      return { ecosystem: "npm", name: parts.join("/") };
    case "maven":
      return parts.length === 2 ? { ecosystem: "Maven", name: parts.join(":") } : null;
    case "nuget":
      return parts.length === 1 ? { ecosystem: "NuGet", name: parts[0]! } : null;
    case "composer":
      return parts.length === 2 ? { ecosystem: "Composer", name: parts.join("/") } : null;
    default:
      return null;
  }
}

function indexComponents(list: unknown, into: Map<string, Json>): void {
  if (!Array.isArray(list)) return;
  for (const c of list) {
    if (!isObject(c)) continue;
    const ref = c["bom-ref"];
    if (typeof ref === "string" && !into.has(ref)) into.set(ref, c);
    indexComponents(c["components"], into);
  }
}

function toDependency(component: Json, source: string): Dependency | null {
  const purl = component["purl"];
  if (typeof purl !== "string") return null;
  const id = fromPurl(purl);
  if (!id) return null;

  const raw = component["version"];
  const text = typeof raw === "string" ? raw.trim() : "";
  const base = { ecosystem: id.ecosystem, name: id.name, source };
  if (!text) return { ...base, version: null, display: "", missing: "no version" };
  const version = normalise(text);
  if (version === null) {
    return { ...base, version: null, display: text, missing: `'${text}' isn't a version` };
  }
  // One rule for every ecosystem: show the resolved version as written in the BOM
  // ("6.2.13.Final", "1.0.0-beta.2"); only `version` is normalised, for matching.
  // A leading "v"/"V" is dropped so Composer's "v10.48.4" shows as "10.48.4".
  return { ...base, version, display: text.replace(/^[vV](?=\d)/, "") };
}

/**
 * Direct dependencies of the root component, in the root's dependsOn order.
 * Never throws: unreadable input gives [] and odd entries are skipped.
 */
export function directDependencies(bom: unknown, source: string, rootRef?: string): Dependency[] {
  if (!isObject(bom)) return [];
  let root = rootRef;
  if (root === undefined) {
    const metadata = bom["metadata"];
    const component = isObject(metadata) ? metadata["component"] : undefined;
    const ref = isObject(component) ? component["bom-ref"] : undefined;
    if (typeof ref !== "string") return [];
    root = ref;
  }
  const entries = bom["dependencies"];
  if (!Array.isArray(entries)) return [];
  const entry = entries.find((e) => isObject(e) && e["ref"] === root);
  const refs = isObject(entry) ? entry["dependsOn"] : undefined;
  if (!Array.isArray(refs)) return [];

  const components = new Map<string, Json>();
  indexComponents(bom["components"], components);

  const out: Dependency[] = [];
  const seen = new Set<string>();
  for (const ref of refs) {
    const component = typeof ref === "string" ? components.get(ref) : undefined;
    if (!component) continue;
    const dep = toDependency(component, source);
    if (!dep) continue;
    const key = `${dep.ecosystem}\u0000${dep.name}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(dep);
  }
  return out;
}
