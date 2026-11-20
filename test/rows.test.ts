import { describe, expect, it } from "vitest";
import { parseCatalogue } from "../src/catalogue.js";
import type { Catalogue } from "../src/catalogue.js";
import { finding } from "../src/models.js";
import type { Dependency, DetectResult, Finding, Unrecognised } from "../src/models.js";
import { buildReport, tidy } from "../src/rows.js";
import type { SbomRow } from "../src/rows.js";
import { FULL, catalogue } from "./fixtures/catalogue.js";

const POM = "pom.xml";
const PKG = "package.json";
const COMPOSER = "composer.json";
const DOCKERFILE = "Dockerfile";

function maven(name: string, version: string | null, source = POM, missing?: string): Dependency {
  return { ecosystem: "Maven", name, version, display: version ?? "set by parent pom", source, missing };
}
function composer(name: string, version: string): Dependency {
  return { ecosystem: "Composer", name, version, display: version, source: COMPOSER };
}
function npm(name: string, version: string): Dependency {
  return { ecosystem: "npm", name, version, display: version, source: PKG };
}
function docker(name: string, tag: string, version: string | null, missing?: string): Dependency {
  return { ecosystem: "Docker", name, version, display: tag, source: DOCKERFILE, missing, tag };
}

function report(
  o: { findings?: Finding[]; dependencies?: Dependency[]; unrecognised?: Unrecognised[]; cat?: Catalogue } = {},
) {
  const result: DetectResult = {
    findings: o.findings ?? [],
    dependencies: o.dependencies ?? [],
    unrecognised: o.unrecognised ?? [],
  };
  return buildReport(result, o.cat ?? catalogue());
}

const sbomRow = (
  ecosystem: string, name: string, version: string, foundIn: string,
  product: string, endOfSupport: string, status: string,
): SbomRow => ({ ecosystem, name, version, foundIn, product, endOfSupport, status });

const triples = (rows: { component: string; version: string; status: string }[]) =>
  rows.map((r) => [r.component, r.version, r.status]);

function rawProduct(name: string, label: string, releases: unknown[]) {
  return { name, label, aliases: [], identifiers: [], releases };
}
function rawRelease(name: string, date: string, isEol: boolean, eol: string | null, latest: string | null) {
  return { name, releaseDate: date, isEol, eolFrom: eol, latest: { name: latest }, codename: null };
}

describe("status rules", () => {
  it("eol row", () => {
    const rep = report({ dependencies: [maven("org.springframework.boot:spring-boot", "3.2.5", "backend/pom.xml")] });
    expect(rep.rows).toEqual([
      { component: "Spring Boot", version: "3.2.5", foundIn: "backend/pom.xml",
        endOfSupport: "2024-12-31", latest: "4.0.1", status: "END OF LIFE" },
    ]);
  });

  it("major-only cycle", () => {
    const [row] = report({ findings: [finding(".NET", "8.0", "net8.0", "api/Api.csproj")] }).rows;
    expect([row.component, row.status, row.endOfSupport]).toEqual([".NET", "supported", "2026-11-10"]);
  });

  it("no EOL date", () => {
    const [row] = report({ dependencies: [npm("react", "17.0.2")] }).rows;
    expect([row.status, row.endOfSupport, row.latest]).toEqual(["no EOL date", "—", "19.2.0"]);
  });

  it("latest drops build metadata", () => {
    const cat = parseCatalogue({ result: [rawProduct("eclipse-temurin", "Eclipse Temurin", [
      rawRelease("27", "2026-09-15", false, "2027-03-23", "27.0.1.0.2+1"),
      rawRelease("17", "2021-09-14", false, "2029-09-30", "17.0.13+11")])] });
    const [row] = report({ findings: [finding("Java", "17", "17", POM)], cat }).rows;
    expect(row.latest).toBe("27.0.1");
  });

  it("tidy keeps normal versions", () => {
    expect(tidy("4.8.1")).toBe("4.8.1");
    expect(tidy("27.0.1.0.2+1")).toBe("27.0.1");
  });

  it("version not found", () => {
    const [row] = report({ dependencies: [npm("react", "15.0.0")] }).rows;
    expect([row.component, row.status, row.endOfSupport]).toEqual(["React", "version not found", "—"]);
  });

  it("runtime slug missing from catalogue", () => {
    const rep = report({ findings: [finding("PHP", "8.1", "8.1", COMPOSER)], cat: parseCatalogue({ result: [] }) });
    expect(rep.rows).toEqual([
      { component: "PHP", version: "8.1", foundIn: "composer.json",
        endOfSupport: "—", latest: "—", status: "version not found" },
    ]);
    expect(rep.sbom).toEqual([sbomRow("Runtime", "PHP", "8.1", "composer.json", "", "", "version not found")]);
  });
});

describe("table rows", () => {
  it("runtime rows bypass merge", () => {
    const src = "Api.csproj";
    const rows = report({ findings: [finding(".NET", "6.0", "net6.0", src), finding(".NET", "8.0", "net8.0", src)] }).rows;
    expect(triples(rows)).toEqual([[".NET", "net6.0", "END OF LIFE"], [".NET", "net8.0", "supported"]]);
  });

  it("exact matches take lowest", () => {
    const rows = report({ dependencies: [
      maven("org.springframework.boot:spring-boot-starter-web", "4.0.1"),
      maven("org.springframework.boot:spring-boot", "3.2.0")] }).rows;
    expect(triples(rows)).toEqual([["Spring Boot", "3.2.0", "END OF LIFE"]]);
  });

  it("versionless members do not decide", () => {
    const rep = report({ dependencies: [
      maven("org.springframework.boot:spring-boot-starter-parent", "3.2.0"),
      maven("org.springframework.boot:spring-boot-starter-web", null, POM, "set by parent pom")] });
    expect(rep.rows.map((r) => [r.component, r.version])).toEqual([["Spring Boot", "3.2.0"]]);
    expect(rep.unrecognised).toEqual([]);
  });

  it("missing version gives one line per product", () => {
    const rep = report({ dependencies: [
      maven("org.springframework.boot:spring-boot-starter-web", null, POM, "set by parent pom"),
      maven("org.springframework.boot:spring-boot", null, POM, "set by parent pom")] });
    expect(rep.unrecognised).toEqual([
      { source: POM, reason: "couldn't read the Spring Boot version (set by parent pom)" }]);
    expect(rep.rows).toEqual([]);
  });

  it("rule matches use most common version", () => {
    const rows = report({ dependencies: [
      composer("symfony/http-kernel", "6.4.1"), composer("symfony/console", "6.4.3"),
      composer("symfony/polyfill-mbstring", "1.28.0")] }).rows;
    expect(triples(rows)).toEqual([["Symfony", "6.4.1", "supported"]]);
  });

  it("untracked not in table but in sbom", () => {
    const rep = report({ dependencies: [npm("left-pad", "1.3.0")] });
    expect(rep.rows).toEqual([]);
    expect(rep.sbom).toEqual([sbomRow("npm", "left-pad", "1.3.0", "package.json", "", "", "")]);
  });
});

describe("Docker", () => {
  it("product and OS rows", () => {
    const rep = report({ dependencies: [docker("node", "18-bullseye", "18")] });
    expect(triples(rep.rows)).toEqual([
      ["Debian", "11 (bullseye)", "END OF LIFE"], ["Node.js", "18-bullseye", "END OF LIFE"]]);
    expect(rep.sbom).toEqual([
      sbomRow("Docker", "Debian", "11 (bullseye)", "Dockerfile", "Debian", "2024-08-14", "END OF LIFE"),
      sbomRow("Docker", "node", "18-bullseye", "Dockerfile", "Node.js", "2025-04-30", "END OF LIFE"),
    ]);
    expect(rep.unrecognised).toEqual([]);
  });

  it("OS image gives a single row", () => {
    const rep = report({ dependencies: [docker("debian", "bookworm-slim", null, "image tag doesn't pin a version")] });
    expect(triples(rep.rows)).toEqual([["Debian", "12 (bookworm)", "supported"]]);
    expect(rep.unrecognised).toEqual([]);
    expect(rep.sbom).toEqual([
      sbomRow("Docker", "debian", "12 (bookworm)", "Dockerfile", "Debian", "2026-06-10", "supported")]);
  });

  it("OS image with numeric tag gives a single sbom row", () => {
    const rep = report({ dependencies: [docker("debian", "12-bookworm", "12")] });
    expect(rep.rows.map((r) => [r.component, r.version])).toEqual([["Debian", "12-bookworm"]]);
    expect(rep.sbom).toEqual([
      sbomRow("Docker", "debian", "12-bookworm", "Dockerfile", "Debian", "2026-06-10", "supported")]);
  });

  it("OS product missing from catalogue is skipped", () => {
    const cat = parseCatalogue({ result: FULL.result.filter((p) => p.name !== "alpine-linux") });
    for (const tag of ["18-alpine", "18-alpine3.19"]) {
      const rep = report({ dependencies: [docker("node", tag, "18")], cat });
      expect(rep.rows.map((r) => r.component)).toEqual(["Node.js"]);
      expect(rep.unrecognised).toEqual([]);
      expect(rep.sbom.map((s) => s.name)).toEqual(["node"]);
    }
  });

  it("unknown image still gets OS row", () => {
    const rep = report({ dependencies: [docker("registry.example.com/java-base", "17-jammy", "17")] });
    expect(rep.rows.map((r) => [r.component, r.version])).toEqual([["Ubuntu", "22.04 (jammy)"]]);
    const image = rep.sbom.find((s) => s.name === "registry.example.com/java-base")!;
    expect([image.product, image.endOfSupport, image.status]).toEqual(["", "", ""]);
  });

  it("multi-stage Dockerfile keeps every sbom row", () => {
    const rep = report({ dependencies: [
      docker("node", "18-bullseye", "18"), docker("python", "3.12-slim-bookworm", "3.12"),
      docker("debian", "12-bookworm", "12"), docker("node", "22-alpine", "22")] });
    const got = rep.sbom.map((s) => [s.name, s.version, s.status]);
    got.sort((a, b) => (a < b ? -1 : a > b ? 1 : 0));
    expect(got).toEqual([
      ["Debian", "11 (bullseye)", "END OF LIFE"],
      ["Debian", "12 (bookworm)", "supported"],
      ["debian", "12-bookworm", "supported"],
      ["node", "18-bullseye", "END OF LIFE"],
      ["node", "22-alpine", "supported"],
      ["python", "3.12-slim-bookworm", ""],
    ]);
  });

  it("unpinned alpine is unrecognised", () => {
    const rep = report({ dependencies: [docker("node", "18-alpine", "18")] });
    expect(rep.rows.map((r) => r.component)).toEqual(["Node.js"]);
    expect(rep.unrecognised).toEqual([
      { source: DOCKERFILE, reason: "couldn't read the Alpine Linux version (Alpine version not pinned)" }]);
  });
});

describe("SBOM", () => {
  it("rule match outside chosen cycle has blank status", () => {
    const sbom = report({ dependencies: [
      composer("symfony/http-kernel", "6.4.1"), composer("symfony/console", "6.4.3"),
      composer("symfony/flex", "2.8.0")] }).sbom;
    const byName = Object.fromEntries(sbom.map((s) => [s.name, s]));
    expect(byName["symfony/flex"]).toEqual(sbomRow("Composer", "symfony/flex", "2.8.0", "composer.json", "Symfony", "", ""));
    expect(byName["symfony/http-kernel"].status).toBe("supported");
  });

  it("exact rows use own version", () => {
    const rep = report({ dependencies: [
      maven("org.hibernate:hibernate-core", "5.6.15"), maven("org.hibernate:hibernate-validator", "6.6.0")] });
    expect(triples(rep.rows)).toEqual([["Hibernate ORM", "5.6.15", "END OF LIFE"]]);
    const byName = Object.fromEntries(rep.sbom.map((s) => [s.name, s]));
    expect(byName["org.hibernate:hibernate-core"].status).toBe("END OF LIFE");
    expect(byName["org.hibernate:hibernate-validator"]).toEqual(
      sbomRow("Maven", "org.hibernate:hibernate-validator", "6.6.0", "pom.xml", "Hibernate ORM", "", ""));
  });

  it("exact members each use own version", () => {
    const sbom = report({ dependencies: [
      maven("org.springframework.boot:spring-boot-starter-web", "4.0.1"),
      maven("org.springframework.boot:spring-boot", "3.2.0")] }).sbom;
    expect(Object.fromEntries(sbom.map((s) => [s.name, s.status]))).toEqual({
      "org.springframework.boot:spring-boot": "END OF LIFE",
      "org.springframework.boot:spring-boot-starter-web": "supported",
    });
  });

  it("runtime sbom rows", () => {
    expect(report({ findings: [finding("Java", "17", "17", POM)] }).sbom).toEqual([
      sbomRow("Runtime", "Java", "17", "pom.xml", "Eclipse Temurin", "2027-10-31", "supported")]);
  });

  it("dedupes on ecosystem, name, source", () => {
    const sbom = report({ dependencies: [npm("react", "17.0.2"), npm("react", "17.0.2")] }).sbom;
    expect(sbom).toEqual([sbomRow("npm", "react", "17.0.2", "package.json", "React", "", "no EOL date")]);
  });

  it("merges identical OS readings", () => {
    const sbom = report({ dependencies: [docker("node", "18-bullseye", "18"), docker("ruby", "3.3-bullseye", "3.3")] }).sbom;
    expect(sbom.filter((s) => s.name === "Debian")).toEqual([
      sbomRow("Docker", "Debian", "11 (bullseye)", "Dockerfile", "Debian", "2024-08-14", "END OF LIFE")]);
  });
});

describe("ordering and pass-through", () => {
  it("sorting", () => {
    const rep = report({
      findings: [finding("Java", "17", "17", "b/pom.xml"), finding("Java", "17", "17", "a/pom.xml")],
      dependencies: [
        maven("org.springframework.boot:spring-boot", "3.2.0", "a/pom.xml"),
        maven("org.hibernate:hibernate-core", "5.6.15", "a/pom.xml")],
    });
    expect(rep.rows.map((r) => [r.foundIn, r.component])).toEqual([
      ["a/pom.xml", "Hibernate ORM"], ["a/pom.xml", "Java"], ["a/pom.xml", "Spring Boot"], ["b/pom.xml", "Java"]]);
    expect(rep.sbom.map((s) => [s.foundIn, s.ecosystem, s.name])).toEqual([
      ["a/pom.xml", "Maven", "org.hibernate:hibernate-core"],
      ["a/pom.xml", "Maven", "org.springframework.boot:spring-boot"],
      ["a/pom.xml", "Runtime", "Java"],
      ["b/pom.xml", "Runtime", "Java"],
    ]);
  });

  it("passes detector unrecognised through and dedupes", () => {
    const gap = { source: POM, reason: "couldn't read the Java version" };
    const rep = report({ unrecognised: [gap, { ...gap }], dependencies: [
      maven("org.springframework.boot:spring-boot", null, POM, "set by parent pom")] });
    expect(rep.unrecognised).toEqual([
      gap, { source: POM, reason: "couldn't read the Spring Boot version (set by parent pom)" }]);
  });

  it("passes hints through unchanged", () => {
    const hints = ["Maven: set JAVA_HOME", "second"];
    expect(buildReport({ findings: [], dependencies: [], unrecognised: [] }, catalogue(), hints).hints).toEqual(hints);
    expect(report().hints).toEqual([]);
  });
});
