/** The full endoflife.date catalogue: download, on-disk cache and parsing. */
import { mkdir, stat, writeFile } from "node:fs/promises";
import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { readText } from "./util.js";

export const FULL_URL = "https://endoflife.date/api/v1/products/full";
const MAX_AGE_MS = 24 * 3600 * 1000;
const CACHE_NAME = "products-full.json";

const VERSION: string = (
  JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8")) as { version: string }
).version;

/** endoflife.date could not be reached or returned something unusable. */
export class ApiUnavailable extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ApiUnavailable";
  }
}

export interface Release {
  name: string;
  releaseDate: string;
  isEol: boolean;
  eolFrom: string | null;
  latest: string | null;
  codename: string | null;
}

export interface Product {
  name: string;
  label: string;
  aliases: string[];
  purls: string[];
  releases: Release[];
}

export class Catalogue {
  constructor(private readonly byName: Map<string, Product>) {}

  product(slug: string): Product | undefined {
    return this.byName.get(slug);
  }

  products(): Product[] {
    return [...this.byName.values()];
  }
}

function parseRelease(raw: any): Release {
  return {
    name: raw.name,
    releaseDate: raw.releaseDate || "",
    isEol: Boolean(raw.isEol),
    eolFrom: raw.eolFrom ?? null,
    latest: raw.latest?.name ?? null,
    codename: raw.codename ?? null,
  };
}

function parseProduct(raw: any): Product {
  if (typeof raw.name !== "string" || !Array.isArray(raw.releases)) {
    throw new TypeError("bad product");
  }
  return {
    name: raw.name,
    label: raw.label || raw.name,
    aliases: [...(raw.aliases ?? [])],
    purls: (raw.identifiers ?? []).filter((i: any) => i.type === "purl").map((i: any) => i.id),
    releases: raw.releases.map(parseRelease),
  };
}

/** Builds a Catalogue from the `/products/full` payload. */
export function parseCatalogue(data: unknown): Catalogue {
  try {
    const products = ((data as any).result as any[]).map(parseProduct);
    return new Catalogue(new Map(products.map((p) => [p.name, p])));
  } catch {
    throw new ApiUnavailable("unexpected catalogue response");
  }
}

export function defaultCacheDir(
  env: NodeJS.ProcessEnv = process.env,
  platform: NodeJS.Platform = process.platform,
  home: string = homedir(),
): string {
  const base =
    platform === "darwin"
      ? join(home, "Library", "Caches")
      : env.XDG_CACHE_HOME || join(home, ".cache");
  return join(base, "eolchecker");
}

async function readCache(path: string): Promise<{ catalogue: Catalogue; mtimeMs: number } | null> {
  try {
    const { mtimeMs } = await stat(path);
    return { catalogue: parseCatalogue(JSON.parse(await readText(path))), mtimeMs };
  } catch {
    return null;
  }
}

async function download(fetchFn: typeof fetch): Promise<unknown> {
  let resp: Response;
  try {
    resp = await fetchFn(FULL_URL, {
      headers: { "User-Agent": `eolchecker/${VERSION}` },
      signal: AbortSignal.timeout(30_000),
      redirect: "follow",
    });
  } catch (err) {
    const e = err as Error;
    throw new ApiUnavailable(e.message || e.name);
  }
  if (resp.status !== 200) throw new ApiUnavailable(`HTTP ${resp.status} from endoflife.date`);
  try {
    return await resp.json();
  } catch {
    throw new ApiUnavailable("endoflife.date returned invalid JSON");
  }
}

function age(ms: number): string {
  const days = Math.floor(ms / 86_400_000);
  if (days >= 1) return `${days} day${days !== 1 ? "s" : ""} ago`;
  const hours = Math.floor(ms / 3_600_000);
  return `${hours} hour${hours !== 1 ? "s" : ""} ago`;
}

export interface LoadOptions {
  cacheFile?: string;
  fetch?: typeof fetch;
  /** Current time in ms since the epoch. */
  now?: number;
  /** Receives the stale-cache warning. Defaults to a no-op. */
  warn?: (msg: string) => void;
}

/**
 * The catalogue from a cache under a day old, else freshly downloaded.
 * If the download fails, an older cached copy is used and `warn` is told.
 */
export async function loadCatalogue(opts: LoadOptions = {}): Promise<Catalogue> {
  const path = opts.cacheFile ?? join(defaultCacheDir(), CACHE_NAME);
  const now = opts.now ?? Date.now();
  const warn = opts.warn ?? (() => {});
  const cached = await readCache(path);
  if (cached && now - cached.mtimeMs < MAX_AGE_MS) return cached.catalogue;
  let data: unknown;
  let catalogue: Catalogue;
  try {
    data = await download(opts.fetch ?? fetch);
    catalogue = parseCatalogue(data);
  } catch (err) {
    if (!cached || !(err instanceof ApiUnavailable)) throw err;
    warn(
      `Couldn't reach endoflife.date (${err.message}); ` +
        `using a cached copy from ${age(now - cached.mtimeMs)}.`,
    );
    return cached.catalogue;
  }
  try {
    await mkdir(dirname(path), { recursive: true });
    await writeFile(path, JSON.stringify(data));
  } catch {
    // The cache is an optimisation; ignore write failures.
  }
  return catalogue;
}
