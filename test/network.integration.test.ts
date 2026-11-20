/**
 * Runs the whole scan against the real endoflife.date API and the real build tools.
 * Opt in with EOLCHECKER_NETWORK=1. Ecosystems whose tool is missing are left out of the repo
 * (and their expectations are skipped), so the test still checks the others.
 */
import { execFile } from "node:child_process";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { homedir, tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { promisify } from "node:util";
import { afterAll, describe, expect, it } from "vitest";
import { scan } from "../src/index.js";
import { findTool } from "../src/tools.js";

const run = promisify(execFile);

// See test/tools.integration.test.ts: dotnet-CycloneDX lives in ~/.dotnet/tools, usually not on PATH.
const env: NodeJS.ProcessEnv = { ...process.env, PATH: `${process.env["PATH"] ?? ""}:${join(homedir(), ".dotnet/tools")}` };
const has = async (...tools: string[]): Promise<boolean> => {
  for (const t of tools) if (!(await findTool(t, env))) return false;
  return true;
};
const haveMaven = await has("mvn");
const haveNpm = await has("npm");
const haveDotnet = await has("dotnet", "dotnet-CycloneDX");
const haveComposer = await has("composer");

const POM = `<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <parent><groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter-parent</artifactId>
  <version>3.1.5</version></parent>
  <artifactId>backend</artifactId>
  <properties><java.version>17</java.version></properties>
  <dependencies>
    <dependency><groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter-web</artifactId></dependency>
    <dependency><groupId>org.springframework</groupId><artifactId>spring-core</artifactId><version>6.0.0</version></dependency>
    <dependency><groupId>org.hibernate.orm</groupId><artifactId>hibernate-core</artifactId><version>6.2.0.Final</version></dependency>
  </dependencies>
</project>`;
const CSPROJ = '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net8.0</TargetFramework></PropertyGroup></Project>';
const PACKAGE_JSON = { name: "frontend", version: "1.0.0", dependencies: { "@angular/core": "16.2.0", angular: "1.8.2", react: "18.2.0", "react-dom": "18.2.0", next: "13.5.0" } };
const COMPOSER = { require: { php: ">=7.4", "laravel/framework": "^10.0", "symfony/http-kernel": "^6.4" } };

const temps: string[] = [];
afterAll(async () => {
  await Promise.all(temps.map((d) => rm(d, { recursive: true, force: true })));
});

async function put(root: string, rel: string, content: string): Promise<void> {
  await mkdir(dirname(join(root, rel)), { recursive: true });
  await writeFile(join(root, rel), content);
}

describe.skipIf(process.env["EOLCHECKER_NETWORK"] !== "1")("mixed repo against the real API", () => {
  it("finds every product, with end-of-life ones flagged", async () => {
    const tmp = await mkdtemp(join(tmpdir(), "eolchecker-network-"));
    temps.push(tmp);
    const root = join(tmp, "repo");
    await put(root, "Dockerfile", "FROM node:18-bullseye\n");
    if (haveMaven) await put(root, "backend/pom.xml", POM);
    if (haveNpm) {
      await put(root, "frontend/package.json", JSON.stringify(PACKAGE_JSON));
      // The npm source needs a lock file; writing one only resolves versions, it installs nothing.
      await run("npm", ["install", "--package-lock-only", "--ignore-scripts"], { cwd: join(root, "frontend"), env });
    }
    if (haveDotnet) await put(root, "api/Api.csproj", CSPROJ);
    if (haveComposer) {
      await put(root, "web/composer.json", JSON.stringify(COMPOSER));
      await run("composer", ["update", "--no-install", "--no-interaction", "--ignore-platform-reqs"], { cwd: join(root, "web"), env });
    }

    const report = await scan(root, { env, cacheDir: join(tmp, "cache") });

    const expected = ["Node.js", "Debian"];
    if (haveMaven) expected.push("Spring Boot", "Spring Framework", "Hibernate ORM", "Java");
    if (haveNpm) expected.push("Angular", "AngularJS", "React", "Next.js");
    if (haveDotnet) expected.push(".NET");
    if (haveComposer) expected.push("Laravel", "Symfony", "PHP");
    const components = new Set(report.rows.map((r) => r.component));
    const detail = JSON.stringify({ rows: report.rows, unrecognised: report.unrecognised });
    for (const c of expected) expect(components, `${c} in ${detail}`).toContain(c);

    expect(report.rows.some((r) => r.status === "END OF LIFE")).toBe(true); // Spring Boot 3.1, Angular 16, Node 18
    expect(report.rows.filter((r) => r.status === "version not found")).toEqual([]);
    expect(report.unrecognised).toEqual([]);
    if (haveMaven) {
      expect(report.sbom).toContainEqual(expect.objectContaining({
        ecosystem: "Maven", name: "org.springframework.boot:spring-boot-starter-web", version: "3.1.5", foundIn: "backend/pom.xml",
      }));
    }
  }, 600_000);

  // A visible skip naming the ecosystems that were left out of the run above.
  const notExercised = [["Maven", haveMaven], ["npm", haveNpm], [".NET", haveDotnet], ["Composer", haveComposer]]
    .filter(([, ok]) => !ok).map(([n]) => n);
  if (notExercised.length) it.skip(`not exercised: ${notExercised.join(", ")} (tool not found)`, () => {});
});
