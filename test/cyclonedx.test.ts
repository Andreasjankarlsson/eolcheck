import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { directDependencies } from "../src/cyclonedx.js";

function load(name: string): unknown {
  return JSON.parse(readFileSync(new URL(`./fixtures/boms/${name}`, import.meta.url), "utf8"));
}

function bomWith(purl: string, version = "1.2.3"): unknown {
  return {
    metadata: { component: { "bom-ref": "root" } },
    components: [{ "bom-ref": "x", name: "x", version, purl }],
    dependencies: [{ ref: "root", dependsOn: ["x"] }],
  };
}

describe("directDependencies", () => {
  it("keeps only direct dependencies", () => {
    const deps = directDependencies(load("minimal-npm.json"), "package.json");
    expect(deps.map((d) => d.name)).toEqual(["@angular/core", "react"]);
    expect(deps[0]).toEqual({
      ecosystem: "npm", name: "@angular/core", version: "16.2.0", display: "16.2.0", source: "package.json",
    });
  });

  it("maps purls to ecosystems and names", () => {
    const cases: [string, string, string][] = [
      ["pkg:npm/%40angular/core@16.2.0", "npm", "@angular/core"],
      ["pkg:npm/react@18.2.0", "npm", "react"],
      ["pkg:maven/org.springframework/spring-core@6.1.0?type=jar", "Maven", "org.springframework:spring-core"],
      ["pkg:nuget/Newtonsoft.Json@13.0.3", "NuGet", "Newtonsoft.Json"],
      ["pkg:composer/laravel/framework@v10.48.4", "Composer", "laravel/framework"],
      ["pkg:composer/a/b@1.0#sub/path", "Composer", "a/b"],
      ["pkg:npm/%E0%A4%A@1.0", "npm", "%E0%A4%A"],
    ];
    for (const [purl, ecosystem, name] of cases) {
      const [dep] = directDependencies(bomWith(purl), "m");
      expect(dep, purl).toMatchObject({ ecosystem, name });
    }
  });

  it("skips unsupported or missing purls", () => {
    expect(directDependencies(bomWith("pkg:pypi/requests@2.0"), "m")).toEqual([]);
    const bom = bomWith("pkg:npm/x@1") as any;
    delete bom.components[0].purl;
    expect(directDependencies(bom, "m")).toEqual([]);
  });

  it("handles unreadable versions without throwing", () => {
    const deps = directDependencies(load("odd-versions.json"), "package.json");
    expect(deps).toHaveLength(3);
    expect(deps.map((d) => [d.version, d.display, d.missing])).toEqual([
      [null, "github:user/repo", "'github:user/repo' isn't a version"],
      [null, "file:../lib", "'file:../lib' isn't a version"],
      [null, "", "no version"],
    ]);
  });

  it("uses rootRef when given and dedupes on ecosystem+name", () => {
    const bom = {
      metadata: { component: { "bom-ref": "root" } },
      components: [
        { "bom-ref": "1", version: "1.0", purl: "pkg:npm/dup@1.0" },
        { "bom-ref": "2", version: "2.0", purl: "pkg:npm/dup@2.0" },
      ],
      dependencies: [{ ref: "other", dependsOn: ["1", "2"] }],
    };
    expect(directDependencies(bom, "m")).toEqual([]);
    const deps = directDependencies(bom, "m", "other");
    expect(deps.map((d) => d.version)).toEqual(["1.0"]);
  });

  it("returns [] when the BOM has no dependencies section", () => {
    expect(directDependencies({ metadata: { component: { "bom-ref": "r" } }, components: [] }, "m")).toEqual([]);
    for (const junk of [null, 5, "x", [], {}, { dependencies: "no", components: 3 }]) {
      expect(directDependencies(junk, "m")).toEqual([]);
    }
  });
});
