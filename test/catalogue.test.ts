import { mkdir, mkdtemp, readFile, stat, utimes, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { describe, expect, it, vi } from "vitest";
import { ApiUnavailable, defaultCacheDir, loadCatalogue, parseCatalogue } from "../src/catalogue.js";
import { FULL, catalogue } from "./fixtures/catalogue.js";

const HOUR = 3600;
const DAY = 24 * HOUR;
const NOW = 10_000_000_000; // ms

const tmp = () => mkdtemp(join(tmpdir(), "eol-cat-"));

function fetching(payload: unknown, calls: Request[] = []): typeof fetch {
  return (async (url: string, init?: RequestInit) => {
    calls.push(new Request(url, init));
    return new Response(JSON.stringify(payload), { status: 200 });
  }) as unknown as typeof fetch;
}
const failing = (async () => {
  throw new TypeError("boom");
}) as unknown as typeof fetch;
const status = (code: number) => (async () => new Response("", { status: code })) as unknown as typeof fetch;

async function writeCache(path: string, ageSec: number, text = JSON.stringify(FULL)) {
  await mkdir(dirname(path), { recursive: true });
  await writeFile(path, text);
  const t = NOW / 1000 - ageSec;
  await utimes(path, t, t);
}

describe("catalogue", () => {
  it("parses the fixture", () => {
    const cat = catalogue();
    const boot = cat.product("spring-boot")!;
    expect(boot.label).toBe("Spring Boot");
    expect(boot.purls).toContain("pkg:maven/org.springframework.boot/spring-boot-starter-web");
    expect(boot.releases[1]).toEqual({
      name: "3.2", releaseDate: "2023-11-23", isEol: true, eolFrom: "2024-12-31",
      latest: "3.2.12", codename: null,
    });
    expect(cat.product("debian")!.releases[0].codename).toBe("Bookworm");
    expect(cat.product("nope")).toBeUndefined();
    expect(cat.products()).toHaveLength(FULL.result.length);
  });

  it("raises on a bad shape", () => {
    expect(() => parseCatalogue({ result: [{ name: "x" }] })).toThrow(ApiUnavailable);
    expect(() => parseCatalogue(null)).toThrow("unexpected catalogue response");
  });

  it("downloads and writes the cache", async () => {
    const cache = join(await tmp(), "c", "products-full.json");
    const calls: Request[] = [];
    const cat = await loadCatalogue({ cacheFile: cache, fetch: fetching(FULL, calls), now: NOW });
    expect(cat.product("php")).toBeDefined();
    expect(JSON.parse(await readFile(cache, "utf8"))).toEqual(FULL);
    expect(calls[0].url).toBe("https://endoflife.date/api/v1/products/full");
    expect(calls[0].headers.get("user-agent")).toBe("eolchecker/0.1.0");
  });

  it("skips the network with a fresh cache", async () => {
    const cache = join(await tmp(), "products-full.json");
    await writeCache(cache, HOUR);
    const cat = await loadCatalogue({ cacheFile: cache, fetch: failing, now: NOW });
    expect(cat.product("php")).toBeDefined();
  });

  it("refreshes an old cache", async () => {
    const cache = join(await tmp(), "products-full.json");
    await writeCache(cache, 25 * HOUR, JSON.stringify({ result: [] }));
    const calls: Request[] = [];
    const cat = await loadCatalogue({ cacheFile: cache, fetch: fetching(FULL, calls), now: NOW });
    expect(calls).toHaveLength(1);
    expect(cat.product("php")).toBeDefined();
    expect(JSON.parse(await readFile(cache, "utf8"))).toEqual(FULL);
  });

  it("uses a stale cache offline and warns", async () => {
    const cache = join(await tmp(), "products-full.json");
    await writeCache(cache, 3 * DAY);
    const warn = vi.fn();
    const cat = await loadCatalogue({ cacheFile: cache, fetch: failing, now: NOW, warn });
    expect(cat.product("php")).toBeDefined();
    expect(warn).toHaveBeenCalledWith(
      "Couldn't reach endoflife.date (boom); using a cached copy from 3 days ago.",
    );
  });

  it("words a single day in the singular", async () => {
    const cache = join(await tmp(), "products-full.json");
    const warn = vi.fn();
    await writeCache(cache, 30 * HOUR);
    await loadCatalogue({ cacheFile: cache, fetch: failing, now: NOW, warn });
    expect(warn.mock.calls[0][0]).toContain("from 1 day ago.");
  });

  it("is silent by default when using a stale cache", async () => {
    const cache = join(await tmp(), "products-full.json");
    await writeCache(cache, 3 * DAY);
    const write = vi.spyOn(process.stderr, "write");
    await loadCatalogue({ cacheFile: cache, fetch: failing, now: NOW });
    expect(write).not.toHaveBeenCalled();
    write.mockRestore();
  });

  it("throws offline without a cache", async () => {
    const cacheFile = join(await tmp(), "products-full.json");
    await expect(loadCatalogue({ cacheFile, fetch: failing, now: NOW })).rejects.toThrow(ApiUnavailable);
  });

  it("ignores a corrupt cache", async () => {
    const cache = join(await tmp(), "products-full.json");
    await writeCache(cache, HOUR, "{");
    await expect(loadCatalogue({ cacheFile: cache, fetch: failing, now: NOW })).rejects.toThrow(ApiUnavailable);
    const cat = await loadCatalogue({ cacheFile: cache, fetch: fetching(FULL), now: NOW });
    expect(cat.product("php")).toBeDefined();
    expect(JSON.parse(await readFile(cache, "utf8"))).toEqual(FULL);
  });

  it("throws on an HTTP error status without a cache", async () => {
    const cacheFile = join(await tmp(), "products-full.json");
    await expect(loadCatalogue({ cacheFile, fetch: status(500), now: NOW })).rejects.toThrow(
      "HTTP 500 from endoflife.date",
    );
  });

  it("ignores a cache write failure", async () => {
    const dir = await tmp();
    await writeFile(join(dir, "file"), "x");
    const cacheFile = join(dir, "file", "products-full.json"); // parent is a file
    const cat = await loadCatalogue({ cacheFile, fetch: fetching(FULL), now: NOW });
    expect(cat.product("php")).toBeDefined();
    await expect(stat(cacheFile)).rejects.toThrow();
  });

  it("picks the cache dir per platform", () => {
    expect(defaultCacheDir({ XDG_CACHE_HOME: "/x" }, "linux", "/h")).toBe("/x/eolchecker");
    expect(defaultCacheDir({}, "linux", "/h")).toBe("/h/.cache/eolchecker");
    expect(defaultCacheDir({}, "darwin", "/h")).toBe("/h/Library/Caches/eolchecker");
  });
});

describe("loadCatalogue signal", () => {
  it("passes a signal that follows the caller's abort to fetch", async () => {
    const dir = await tmp();
    const controller = new AbortController();
    let seen: AbortSignal | undefined | null;
    const f = (async (_url: string, init?: RequestInit) => {
      seen = init?.signal;
      return new Response(JSON.stringify(FULL), { status: 200 });
    }) as unknown as typeof fetch;
    await loadCatalogue({ cacheFile: join(dir, "c.json"), fetch: f, signal: controller.signal });
    expect(seen?.aborted).toBe(false);
    controller.abort();
    expect(seen?.aborted).toBe(true);
  });
});
