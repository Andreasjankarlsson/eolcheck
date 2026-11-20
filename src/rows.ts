/** Turn detector output into table rows, SBOM rows and "Not recognised" lines. */
import type { Catalogue, Product, Release } from "./catalogue.js";
import { Matcher, osFromTag } from "./matching.js";
import type { DetectResult, Unrecognised } from "./models.js";
import { cycleCandidates } from "./versions.js";

export const DASH = "—";

export interface Row {
  component: string;
  version: string;
  foundIn: string;
  endOfSupport: string;
  latest: string;
  status: string;
}

export interface SbomRow {
  ecosystem: string;
  name: string;
  version: string;
  foundIn: string;
  product: string;
  endOfSupport: string;
  status: string;
}

export interface Report {
  rows: Row[];
  sbom: SbomRow[];
  unrecognised: Unrecognised[];
  hints: string[];
}

/** One dependency or OS reading that belongs to a product in a file. */
interface Member {
  version: string | null;
  display: string;
  byRule: boolean;
  missing?: string;
  /** [ecosystem, name]; undefined for an unreadable OS. */
  sbom?: [string, string];
}

function match(version: string, releases: Release[]): Release | null {
  const byName = new Map(releases.map((r) => [r.name, r]));
  for (const candidate of cycleCandidates(version)) {
    const hit = byName.get(candidate);
    if (hit) return hit;
  }
  return null;
}

/** '27.0.1.0.2+1' -> '27.0.1': drop build metadata and anything past major.minor.patch. */
export function tidy(version: string): string {
  const core = version.split("+")[0];
  if (/^\d+(?:\.\d+)*$/.test(core)) return core.split(".").slice(0, 3).join(".");
  return version;
}

function newestLatest(releases: Release[]): string {
  if (releases.length === 0) return DASH;
  let newest = releases[0];
  for (const r of releases) if (r.releaseDate > newest.releaseDate) newest = r;
  return tidy(newest.latest || newest.name);
}

function status(
  version: string,
  product: Product | undefined,
): { release: Release | null; eos: string | null; text: string } {
  const release = product ? match(version, product.releases) : null;
  if (release === null) return { release: null, eos: null, text: "version not found" };
  if (release.isEol) return { release, eos: release.eolFrom, text: "END OF LIFE" };
  if (release.eolFrom === null) return { release, eos: null, text: "no EOL date" };
  return { release, eos: release.eolFrom, text: "supported" };
}

function key(version: string): number[] {
  return (version.match(/\d+/g) ?? []).map(Number);
}

/** Tuple comparison: element-wise, a shorter prefix sorts lower. */
function compareKeys(a: number[], b: number[]): number {
  const n = Math.min(a.length, b.length);
  for (let i = 0; i < n; i++) if (a[i] !== b[i]) return a[i] < b[i] ? -1 : 1;
  return a.length - b.length;
}

function cmpStr(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

/** The first of several equal minima wins. */
function minBy<T>(items: T[], cmp: (a: T, b: T) => number): T {
  let best = items[0];
  for (const item of items) if (cmp(item, best) < 0) best = item;
  return best;
}

/** The member whose version the product row shows. */
function choose(members: Member[], product: Product): Member | null {
  const versioned = members.filter((m) => m.version);
  if (versioned.length === 0) return null;
  const byVersion = (a: Member, b: Member) => compareKeys(key(a.version!), key(b.version!));
  const exact = versioned.filter((m) => !m.byRule);
  if (exact.length > 0) return minBy(exact, byVersion);
  const names = new Set(product.releases.map((r) => r.name));
  const cycles = new Map<string, Member[]>();
  for (const m of versioned) {
    const cycle = cycleCandidates(m.version!).find((c) => names.has(c)) ?? m.version!;
    let list = cycles.get(cycle);
    if (!list) cycles.set(cycle, (list = []));
    list.push(m);
  }
  const best = minBy([...cycles.keys()], (a, b) => {
    const bySize = cycles.get(b)!.length - cycles.get(a)!.length;
    return bySize !== 0 ? bySize : compareKeys(key(a), key(b));
  });
  return minBy(cycles.get(best)!, byVersion);
}

export function buildReport(
  result: DetectResult,
  catalogue: Catalogue,
  hints: string[] = [],
): Report {
  const matcher = new Matcher(catalogue);
  const rows: Row[] = [];
  const sbom: SbomRow[] = [];
  const gaps: Unrecognised[] = [...result.unrecognised];

  for (const f of result.findings) {
    const product = catalogue.product(f.product);
    const { eos, text } = status(f.version, product);
    rows.push({
      component: f.component,
      version: f.display,
      foundIn: f.source,
      endOfSupport: eos || DASH,
      latest: product ? newestLatest(product.releases) : DASH,
      status: text,
    });
    sbom.push({
      ecosystem: "Runtime",
      name: f.component,
      version: f.display,
      foundIn: f.source,
      product: product ? product.label : "",
      endOfSupport: eos || "",
      status: text,
    });
  }

  // Keyed by product slug + NUL + source; Map keeps first-seen order.
  const groups = new Map<string, { slug: string; source: string; members: Member[] }>();
  const addMember = (slug: string, source: string, member: Member) => {
    const k = `${slug}\0${source}`;
    let g = groups.get(k);
    if (!g) groups.set(k, (g = { slug, source, members: [] }));
    g.members.push(member);
  };

  for (const dep of result.dependencies) {
    const m = matcher.match(dep);
    let version = dep.version;
    let display = dep.display;
    if (dep.ecosystem === "Docker" && dep.tag) {
      const reading = osFromTag(dep.tag, catalogue);
      for (const hit of reading.hits) {
        const osProduct = catalogue.product(hit.product);
        if (!osProduct) continue;
        if (m && hit.product === m.product) {
          if (version === null) {
            // the image is the OS itself: one row, from the codename
            version = hit.version;
            display = hit.display;
          }
          continue;
        }
        addMember(hit.product, dep.source, {
          version: hit.version,
          display: hit.display,
          byRule: false,
          sbom: ["Docker", osProduct.label],
        });
      }
      for (const [slug, reason] of reading.missing) {
        if (catalogue.product(slug)) {
          addMember(slug, dep.source, { version: null, display: "", byRule: false, missing: reason });
        }
      }
    }
    if (m === null) {
      sbom.push({
        ecosystem: dep.ecosystem,
        name: dep.name,
        version: display,
        foundIn: dep.source,
        product: "",
        endOfSupport: "",
        status: "",
      });
      continue;
    }
    addMember(m.product, dep.source, {
      version,
      display,
      byRule: m.byRule,
      missing: version ? undefined : dep.missing,
      sbom: [dep.ecosystem, dep.name],
    });
  }

  for (const { slug, source, members } of groups.values()) {
    const product = catalogue.product(slug)!;
    const chosen = choose(members, product);
    let chosenRelease: Release | null = null;
    if (chosen === null) {
      const reason = members.find((m) => m.missing)?.missing;
      gaps.push({
        source,
        reason: `couldn't read the ${product.label} version` + (reason ? ` (${reason})` : ""),
      });
    } else {
      const s = status(chosen.version!, product);
      chosenRelease = s.release;
      rows.push({
        component: product.label,
        version: chosen.display,
        foundIn: source,
        endOfSupport: s.eos || DASH,
        latest: newestLatest(product.releases),
        status: s.text,
      });
    }
    for (const m of members) {
      if (!m.sbom) continue;
      let eos = "";
      let text = "";
      if (m.version) {
        const own = status(m.version, product);
        // A Docker image matched by name is that product itself, so its own version always counts.
        if (!m.byRule || m.sbom[0] === "Docker" || (own.release !== null && own.release === chosenRelease)) {
          eos = own.eos || "";
          text = own.text;
        }
      }
      sbom.push({
        ecosystem: m.sbom[0],
        name: m.sbom[1],
        version: m.display,
        foundIn: source,
        product: product.label,
        endOfSupport: eos,
        status: text,
      });
    }
  }

  const seen = new Map<string, SbomRow>();
  for (const s of sbom) {
    // Runtimes and Docker images can repeat in one file with different versions (e.g. multi-stage builds).
    const parts = [s.ecosystem, s.name, s.foundIn];
    if (s.ecosystem === "Runtime" || s.ecosystem === "Docker") parts.push(s.version);
    const k = JSON.stringify(parts);
    if (!seen.has(k)) seen.set(k, s);
  }

  const gapSeen = new Set<string>();
  const unrecognised = gaps.filter((g) => {
    const k = JSON.stringify([g.source, g.reason]);
    if (gapSeen.has(k)) return false;
    gapSeen.add(k);
    return true;
  });

  rows.sort((a, b) => cmpStr(a.foundIn, b.foundIn) || cmpStr(a.component, b.component));
  return {
    rows,
    sbom: [...seen.values()].sort(
      (a, b) => cmpStr(a.foundIn, b.foundIn) || cmpStr(a.ecosystem, b.ecosystem) || cmpStr(a.name, b.name),
    ),
    unrecognised,
    hints,
  };
}
