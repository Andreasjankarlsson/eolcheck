/**
 * Runs the real build tools over the fixture projects. Opt in with EOLCHECKER_TOOLS=1.
 * The assertions mirror the unit tests, which use recorded BOMs, so a drift between a
 * recording (or a hand-written BOM) and the real tool shows up here.
 */
import { cp, mkdtemp, rm } from "node:fs/promises";
import { homedir, tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it } from "vitest";
import { scan, type Report } from "../src/index.js";
import { findTool } from "../src/tools.js";
import { catalogue } from "./fixtures/catalogue.js";

const PROJECTS = join(dirname(fileURLToPath(import.meta.url)), "fixtures", "projects");
const TIMEOUT = 300_000; // the first Maven / NuGet run downloads plugins and packages

// `dotnet tool install --global` puts dotnet-CycloneDX in ~/.dotnet/tools, which is usually not on PATH
// for GUI apps (Electron) or Jenkins agents. Callers of scan() pass the extended PATH through `env`.
const env: NodeJS.ProcessEnv = { ...process.env, PATH: `${process.env["PATH"] ?? ""}:${join(homedir(), ".dotnet/tools")}` };

const available = async (...tools: string[]): Promise<string | null> => {
  for (const t of tools) if (!(await findTool(t, env))) return t;
  return null;
};

const missing = {
  maven: await available("mvn"),
  npm: await available("npm"),
  dotnet: await available("dotnet", "dotnet-CycloneDX"),
  composer: await available("composer"),
};

const temps: string[] = [];
afterEach(async () => {
  await Promise.all(temps.splice(0).map((d) => rm(d, { recursive: true, force: true })));
});

/** Scan a fresh copy of a fixture so tool output (target/, obj/, bin/) never lands in the repo. */
async function scanFixture(name: string): Promise<Report> {
  const dir = await mkdtemp(join(tmpdir(), `eolchecker-${name}-`));
  temps.push(dir);
  await cp(join(PROJECTS, name), dir, { recursive: true });
  return scan(dir, { env, catalogue: async () => catalogue() });
}

const deps = (r: Report, ecosystem: string): string[][] =>
  r.sbom.filter((s) => s.ecosystem === ecosystem).map((s) => [s.name, s.version, s.foundIn]);
const runtimes = (r: Report): string[][] =>
  r.rows.map((x) => [x.component, x.version, x.foundIn]);

const label = (name: string, tool: string | null): string =>
  tool ? `${name} (skipped: ${tool} not found)` : name;

describe.skipIf(process.env["EOLCHECKER_TOOLS"] !== "1")("real tools", () => {
  it.skipIf(missing.maven)(label("Maven reads direct dependencies and Java", missing.maven), async () => {
    const r = await scanFixture("maven-multi");
    expect(r.unrecognised).toEqual([]);
    expect(deps(r, "Maven")).toEqual([
      ["junit:junit", "4.13.2", "app/pom.xml"],
      ["org.springframework.boot:spring-boot-starter-web", "3.3.5", "app/pom.xml"],
    ]);
    expect(r.sbom.filter((s) => s.ecosystem === "Runtime").map((s) => [s.name, s.version, s.foundIn])).toEqual([
      ["Java", "17", "app/pom.xml"],
    ]);
  }, TIMEOUT);

  it.skipIf(missing.npm)(label("npm reads dependencies of an app", missing.npm), async () => {
    const r = await scanFixture("npm-app");
    expect(r.unrecognised).toEqual([]);
    expect(deps(r, "npm")).toEqual([
      ["is-number", "7.0.0", "package.json"],
      ["left-pad", "1.3.0", "package.json"],
      ["ms", "2.1.3", "package.json"],
    ]);
    expect(runtimes(r)).toEqual([["Node.js", ">=18", "package.json"]]);
  }, TIMEOUT);

  it.skipIf(missing.npm)(label("npm reads a workspace member from the root lock", missing.npm), async () => {
    const r = await scanFixture("npm-workspace");
    expect(r.unrecognised).toEqual([]);
    expect(deps(r, "npm").filter((d) => d[2] === "packages/a/package.json")).toEqual([
      ["is-number", "7.0.0", "packages/a/package.json"],
      ["left-pad", "1.3.0", "packages/a/package.json"],
    ]);
  }, TIMEOUT);

  it.skipIf(missing.dotnet)(label("dotnet reads package references and target framework", missing.dotnet), async () => {
    const r = await scanFixture("dotnet-cpm");
    expect(r.unrecognised).toEqual([]);
    expect(deps(r, "NuGet")).toEqual([
      ["Newtonsoft.Json", "13.0.3", "src/Api/Api.csproj"],
      ["Serilog", "3.1.0", "src/Api/Api.csproj"],
    ]);
    expect(runtimes(r)).toEqual([
      [".NET", "SDK 8.0.100", "global.json"],
      [".NET", "net8.0", "src/Api/Api.csproj"],
    ]);
  }, TIMEOUT);

  it.skipIf(missing.composer)(label("Composer reads require and require-dev", missing.composer), async () => {
    const r = await scanFixture("composer-app");
    expect(r.unrecognised).toEqual([]);
    expect(deps(r, "Composer")).toEqual([
      ["laravel/framework", "10.48.4", "composer.json"],
      ["phpunit/phpunit", "10.5.0", "composer.json"],
    ]);
    expect(runtimes(r)).toEqual([["PHP", "^8.1", "composer.json"]]);
  }, TIMEOUT);
});
