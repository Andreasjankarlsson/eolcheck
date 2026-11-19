import { mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { main } from "../src/cli.js";
import { ApiUnavailable, type Report } from "../src/index.js";

const ANGULAR: Report = {
  rows: [
    {
      component: "Angular",
      version: "16.2.0",
      foundIn: "frontend/package.json",
      endOfSupport: "2023-11-08",
      latest: "20.3.0",
      status: "END OF LIFE",
    },
  ],
  sbom: [
    {
      ecosystem: "npm",
      name: "@angular/core",
      version: "16.2.0",
      foundIn: "frontend/package.json",
      product: "Angular",
      endOfSupport: "2023-11-08",
      status: "END OF LIFE",
    },
  ],
  unrecognised: [],
  hints: [],
};
const EMPTY: Report = { rows: [], sbom: [], unrecognised: [], hints: [] };

let root: string;
let tmp: string;
beforeEach(async () => {
  tmp = await mkdtemp(join(tmpdir(), "cli-"));
  root = join(tmp, "repo");
  await mkdir(root);
});
afterEach(async () => {
  await rm(tmp, { recursive: true, force: true });
});

async function run(argv: string[], report: Report | Error = ANGULAR, isTTY = false) {
  let out = "";
  let err = "";
  const scan = vi.fn(async (_root: string, _options?: unknown) => {
    if (report instanceof Error) throw report;
    return report;
  });
  const code = await main(argv, {
    scan,
    stdout: (s) => (out += s),
    stderr: (s) => (err += s),
    isTTY,
  });
  return { code, out, err, scan };
}

describe("main", () => {
  it("prints the table", async () => {
    const { code, out } = await run([root]);
    expect(code).toBe(0);
    for (const text of ["Angular", "16.2.0", "frontend/package.json", "END OF LIFE", "Latest", "20.3.0", "repo"]) {
      expect(out).toContain(text);
    }
    expect(out.endsWith("\n\n")).toBe(true);
  });

  it("exits 2 for a missing path", async () => {
    const { code, err, scan } = await run(["/nope"]);
    expect(code).toBe(2);
    expect(err).toContain("Path not found: /nope");
    expect(scan).not.toHaveBeenCalled();
  });

  it("exits 2 for a file instead of a folder", async () => {
    const file = join(root, "package.json");
    await writeFile(file, "{}");
    const { code, err } = await run([file]);
    expect(code).toBe(2);
    expect(err).toContain(`Not a folder: ${file}`);
  });

  it("reports a missing ~ path as typed", async () => {
    const { code, err } = await run(["~/definitely-not-here-eolchecker"]);
    expect(code).toBe(2);
    expect(err).toContain("Path not found: ~/definitely-not-here-eolchecker");
  });

  it("passes the resolved absolute root to scan", async () => {
    const { scan } = await run([root]);
    expect(scan.mock.calls[0][0]).toBe(root);
  });

  it("exits 1 when the catalogue is unavailable", async () => {
    const { code, err } = await run([root], new ApiUnavailable("timed out"));
    expect(code).toBe(1);
    expect(err).toContain("Couldn't fetch end-of-life dates from endoflife.date: timed out");
  });

  it("shows the not recognised section", async () => {
    const gap = { ...EMPTY, unrecognised: [{ source: "tools/pom.xml", reason: "couldn't read the Spring Boot version" }] };
    const { code, out } = await run([root], gap);
    expect(code).toBe(0);
    expect(out).toContain("Not recognised:");
    expect(out).toContain("tools/pom.xml: couldn't read the Spring Boot version");
  });

  it("says when nothing is found", async () => {
    const { code, out } = await run([root], EMPTY);
    expect(code).toBe(0);
    expect(out).toContain(`No dependencies found in ${root}`);
  });

  it("says when nothing is tracked", async () => {
    const untracked = { ...EMPTY, sbom: ANGULAR.sbom };
    const { code, out } = await run([root], untracked);
    expect(code).toBe(0);
    expect(out).toContain("No dependencies tracked by endoflife.date found.");
  });

  it("writes a CSV SBOM", async () => {
    const file = join(tmp, "sbom.csv");
    const { code, out } = await run([root, "--sbom", file]);
    expect(code).toBe(0);
    const lines = (await readFile(file, "utf8")).split("\n");
    expect(lines[0]).toBe("Ecosystem,Name,Version,Found in,Product,End of support,Status");
    expect(lines.slice(1).some((l) => l.includes("@angular/core") && l.includes("16.2.0"))).toBe(true);
    expect(out).toContain("END OF LIFE");
    expect(out).toContain(`SBOM written to ${file}`);
    expect(out.indexOf("SBOM written")).toBeGreaterThan(out.indexOf("END OF LIFE"));
  });

  it("writes a Markdown SBOM", async () => {
    const file = join(tmp, "sbom.md");
    const { code } = await run([root, "--sbom", file]);
    expect(code).toBe(0);
    const lines = (await readFile(file, "utf8")).split("\n");
    expect(lines[0].startsWith("| Ecosystem | Name |")).toBe(true);
    expect(lines.slice(2).some((l) => l.includes("@angular/core"))).toBe(true);
  });

  it("writes a header-only SBOM when nothing is found", async () => {
    const file = join(tmp, "sbom.csv");
    const { code, out } = await run([root, "--sbom", file], EMPTY);
    expect(code).toBe(0);
    expect(await readFile(file, "utf8")).toBe("Ecosystem,Name,Version,Found in,Product,End of support,Status\n");
    expect(out).toContain("No dependencies found in");
    expect(out).toContain(`SBOM written to ${file}`);
  });

  it("rejects a bad --sbom extension before scanning", async () => {
    const { code, err, scan } = await run(["/nope", "--sbom", "out.txt"]);
    expect(code).toBe(2);
    expect(err).toContain("--sbom file must end in .csv or .md");
    expect(scan).not.toHaveBeenCalled();
  });

  it("exits 1 when the SBOM can't be written", async () => {
    const file = join(tmp, "missing", "sbom.csv");
    const { code, err, out } = await run([root, "--sbom", file]);
    expect(code).toBe(1);
    expect(err).toContain("Couldn't write");
    expect(out).toContain("END OF LIFE");
  });

  it("prints the report as JSON with --json", async () => {
    const { code, out } = await run([root, "--json"]);
    expect(code).toBe(0);
    const parsed = JSON.parse(out);
    expect(Object.keys(parsed).sort()).toEqual(["hints", "rows", "sbom", "unrecognised"]);
    expect(out).not.toContain("Component");
  });

  it("still writes the SBOM with --json", async () => {
    const file = join(tmp, "sbom.csv");
    const { code, out, err } = await run([root, "--json", "--sbom", file]);
    expect(code).toBe(0);
    expect(await readFile(file, "utf8")).toContain("@angular/core");
    expect(JSON.parse(out).rows).toHaveLength(1);
    expect(out).not.toContain("SBOM written");
    expect(err).toContain(`SBOM written to ${file}`);
  });

  it("rejects an empty --sbom value", async () => {
    const { code, err, scan } = await run([root, "--sbom", ""]);
    expect(code).toBe(2);
    expect(err).toContain("--sbom file must end in .csv or .md");
    expect(scan).not.toHaveBeenCalled();
  });

  it("reports unexpected scan errors on one line and exits 1", async () => {
    const { code, err } = await run([root], new Error("boom"));
    expect(code).toBe(1);
    expect(err).toBe("eolchecker: unexpected error: boom\n");
  });

  it("rejects --no-maven", async () => {
    const { code, err } = await run([root, "--no-maven"]);
    expect(code).toBe(2);
    expect(err).not.toBe("");
  });

  it("exits 0 when something is END OF LIFE", async () => {
    expect((await run([root])).code).toBe(0);
  });

  it("uses colour only on a TTY", async () => {
    expect((await run([root], ANGULAR, true)).out).toContain("\x1b[");
    expect((await run([root], ANGULAR, false)).out).not.toContain("\x1b[");
  });

  it("sends progress and warnings to stderr and passes the CLI's env", async () => {
    let out = "";
    let err = "";
    const scan = vi.fn(async (_r: string, o?: { onProgress?: (m: string) => void; warn?: (m: string) => void }) => {
      o?.onProgress?.("running mvn");
      o?.warn?.("stale cache");
      return EMPTY;
    });
    await main([root], { scan, stdout: (s) => (out += s), stderr: (s) => (err += s), isTTY: false });
    expect(err).toContain("running mvn\n");
    expect(err).toContain("stale cache\n");
    expect(out).not.toContain("running mvn");
    expect(scan.mock.calls[0][1]).toMatchObject({ env: process.env });
  });

  it("prints usage for --help", async () => {
    const { code, out } = await run(["--help"]);
    expect(code).toBe(0);
    expect(out).toContain("Usage: eolchecker");
  });

  it("exits 2 without a path", async () => {
    const { code, err } = await run([]);
    expect(code).toBe(2);
    expect(err).toContain("Usage: eolchecker");
  });
});
