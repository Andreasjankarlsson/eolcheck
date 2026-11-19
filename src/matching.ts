/** Match detected dependencies to endoflife.date products by package URL. */
import type { Catalogue } from "./catalogue.js";
import type { Dependency } from "./models.js";

const DOCKER_HUBS = ["docker.io/", "index.docker.io/", "registry-1.docker.io/"];

function unquote(text: string): string {
  try {
    return decodeURIComponent(text);
  } catch {
    return text;
  }
}

function partition(text: string, sep: string): [string, string] {
  const i = text.indexOf(sep);
  return i < 0 ? [text, ""] : [text.slice(0, i), text.slice(i + sep.length)];
}

/** Canonical form: no version, no qualifiers (bar repository_url for docker/oci), decoded, lower-cased. */
export function normalisePurl(purl: string): string {
  const [base, query] = partition(purl, "?");
  let kept = "";
  if (base.startsWith("pkg:docker/") || base.startsWith("pkg:oci/")) {
    for (const part of query.split("&")) {
      if (part.startsWith("repository_url=")) kept = "?" + part;
    }
  }
  const slash = base.lastIndexOf("/");
  const head = base.slice(0, slash + 1);
  let last = base.slice(slash + 1);
  if (!last.startsWith("@")) {
    const at = last.lastIndexOf("@");
    if (at >= 0) last = last.slice(0, at);
  }
  const path = unquote(head + last);
  if (path.startsWith("pkg:maven/")) return path + kept.toLowerCase();
  return (path + kept).toLowerCase();
}

function stripHub(image: string): string {
  const lower = image.toLowerCase();
  for (const hub of DOCKER_HUBS) {
    if (lower.startsWith(hub)) return lower.slice(hub.length);
  }
  return lower;
}

function stripLibrary(image: string): string {
  return image.startsWith("library/") ? image.slice("library/".length) : image;
}

export function dockerPurl(image: string): string {
  let img = stripHub(image);
  const parts = img.split("/");
  const first = parts[0];
  if (parts.length > 1 && (first.includes(".") || first.includes(":") || first === "localhost")) {
    return `pkg:oci/${parts[parts.length - 1]}?repository_url=${parts.slice(0, -1).join("/")}`;
  }
  if (parts.length === 1) img = "library/" + img;
  return `pkg:docker/${img}`;
}

export function isOfficialImage(image: string): boolean {
  return !stripLibrary(stripHub(image)).includes("/");
}

export function dependencyPurl(dep: Dependency): string {
  if (dep.ecosystem === "Docker") return dockerPurl(dep.name);
  if (dep.ecosystem === "Maven") {
    const [group, artifact] = partition(dep.name, ":");
    return normalisePurl(`pkg:maven/${group}/${artifact}`);
  }
  return `pkg:${dep.ecosystem.toLowerCase()}/${dep.name.toLowerCase()}`;
}

export interface Match {
  product: string;
  byRule: boolean;
}

function claim(map: Map<string, Set<string>>, key: string, slug: string): void {
  let set = map.get(key);
  if (!set) map.set(key, (set = new Set()));
  set.add(slug);
}

/** Keep only keys claimed by exactly one product. */
function unique(claims: Map<string, Set<string>>): Map<string, string> {
  const out = new Map<string, string>();
  for (const [key, slugs] of claims) {
    if (slugs.size === 1) out.set(key, [...slugs][0]);
  }
  return out;
}

export class Matcher {
  private readonly exact = new Map<string, string>();
  private readonly groups: Map<string, string>;
  private readonly vendors: Map<string, string>;
  private readonly names: Map<string, string>;

  constructor(c: Catalogue) {
    const groups = new Map<string, Set<string>>();
    const vendors = new Map<string, Set<string>>();
    const names = new Map<string, Set<string>>();
    for (const product of c.products()) {
      const normalised = product.purls.map(normalisePurl);
      for (const purl of normalised) {
        if (!this.exact.has(purl)) this.exact.set(purl, product.name);
        const segments = purl.split("/");
        if (purl.startsWith("pkg:maven/") && segments.length - 1 >= 2) {
          claim(groups, segments[1], product.name);
        }
      }
      const labels = new Set([
        product.name.toLowerCase(),
        ...product.aliases.map((a) => a.toLowerCase()),
      ]);
      const composer = normalised.some((p) => p.startsWith("pkg:composer/"));
      for (const label of labels) {
        claim(names, label, product.name);
        if (!composer) claim(vendors, label, product.name);
      }
    }
    this.groups = unique(groups);
    this.vendors = unique(vendors);
    this.names = unique(names);
  }

  match(dep: Dependency): Match | null {
    const exact = this.exact.get(dependencyPurl(dep));
    if (exact) return { product: exact, byRule: false };
    let slug: string | undefined;
    if (dep.ecosystem === "Maven") {
      slug = this.groups.get(partition(dep.name, ":")[0]);
    } else if (dep.ecosystem === "Composer") {
      slug = this.vendors.get(partition(dep.name.toLowerCase(), "/")[0]);
    } else if (dep.ecosystem === "Docker" && isOfficialImage(dep.name)) {
      slug = this.names.get(stripLibrary(stripHub(dep.name)));
    }
    return slug ? { product: slug, byRule: true } : null;
  }
}

export const ALPINE = "alpine-linux";
const CODENAME_PRODUCTS = ["debian", "ubuntu"];
const ALPINE_PART = /^alpine(\d+(?:\.\d+)*)$/;

export interface OsHit {
  product: string;
  version: string;
  display: string;
}

/** Read the base OS named by a Docker tag: Alpine version or Debian/Ubuntu codename. */
export function osFromTag(
  tag: string,
  c: Catalogue,
): { hits: OsHit[]; missing: [string, string][] } {
  const codenames = new Map<string, [string, string]>();
  for (const slug of CODENAME_PRODUCTS) {
    for (const release of c.product(slug)?.releases ?? []) {
      const word = (release.codename ?? "").split(/\s+/).find((w) => w !== "");
      if (word && !codenames.has(word.toLowerCase())) {
        codenames.set(word.toLowerCase(), [slug, release.name]);
      }
    }
  }
  const hits: OsHit[] = [];
  const missing: [string, string][] = [];
  for (const part of tag.split("-").map((p) => p.toLowerCase())) {
    const alpine = ALPINE_PART.exec(part);
    const named = codenames.get(part);
    if (alpine) {
      hits.push({ product: ALPINE, version: alpine[1], display: alpine[1] });
    } else if (part === "alpine") {
      missing.push([ALPINE, "Alpine version not pinned"]);
    } else if (named) {
      hits.push({ product: named[0], version: named[1], display: `${named[1]} (${part})` });
    }
  }
  return { hits, missing };
}
