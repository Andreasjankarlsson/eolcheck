import { describe, expect, it } from "vitest";
import { parseCatalogue } from "../src/catalogue.js";
import {
  Matcher,
  dockerPurl,
  isOfficialImage,
  normalisePurl,
  osFromTag,
} from "../src/matching.js";
import type { Dependency, Ecosystem } from "../src/models.js";
import { catalogue } from "./fixtures/catalogue.js";

describe("normalisePurl", () => {
  it.each([
    ["pkg:npm/%40angular/core", "pkg:npm/@angular/core"],
    ["pkg:npm/React@18.2.0", "pkg:npm/react"],
    ["pkg:maven/org.Foo/Bar@1.0?type=jar", "pkg:maven/org.Foo/Bar"],
    ["pkg:nuget/Microsoft.NETCore.App", "pkg:nuget/microsoft.netcore.app"],
    [
      "pkg:oci/deno?repository_url=ghcr.io/denoland",
      "pkg:oci/deno?repository_url=ghcr.io/denoland",
    ],
    ["pkg:docker/library/node?tag=18", "pkg:docker/library/node"],
    ["pkg:npm/100%/x", "pkg:npm/100%/x"],
  ])("%s", (raw, expected) => {
    expect(normalisePurl(raw)).toBe(expected);
  });
});

describe("dockerPurl", () => {
  it.each([
    ["node", "pkg:docker/library/node"],
    ["docker.io/library/node", "pkg:docker/library/node"],
    ["index.docker.io/bitnami/node", "pkg:docker/bitnami/node"],
    ["ghcr.io/denoland/deno", "pkg:oci/deno?repository_url=ghcr.io/denoland"],
    ["localhost:5000/app", "pkg:oci/app?repository_url=localhost:5000"],
  ])("%s", (image, expected) => {
    expect(dockerPurl(image)).toBe(expected);
  });
});

it("recognises official images", () => {
  expect(isOfficialImage("php")).toBe(true);
  expect(isOfficialImage("library/php")).toBe(true);
  expect(isOfficialImage("docker.io/php")).toBe(true);
  expect(isOfficialImage("myorg/php")).toBe(false);
  expect(isOfficialImage("ghcr.io/x/php")).toBe(false);
});

const M = new Matcher(catalogue());

function dep(ecosystem: Ecosystem, name: string): Dependency {
  return { ecosystem, name, version: "1.0", display: "1.0", source: "f" };
}

describe("Matcher.match", () => {
  it.each<[Ecosystem, string, string, boolean]>([
    ["npm", "@angular/core", "angular", false],
    ["npm", "React", "react", false],
    ["Maven", "org.springframework.boot:spring-boot-starter-web", "spring-boot", false],
    ["Maven", "org.springframework.boot:spring-boot-starter-parent", "spring-boot", true],
    ["Maven", "org.hibernate:hibernate-core", "hibernate-orm", false],
    ["NuGet", "microsoft.netcore.app", "dotnet", false],
    ["Composer", "laravel/framework", "laravel", false],
    ["Composer", "symfony/http-kernel", "symfony", true],
    ["Docker", "node", "nodejs", false],
    ["Docker", "ghcr.io/denoland/deno", "deno", false],
    ["Docker", "php", "php", true],
    ["Docker", "alpine", "alpine-linux", true],
    ["Docker", "eclipse-temurin", "eclipse-temurin", true],
  ])("%s %s", (eco, name, product, byRule) => {
    expect(M.match(dep(eco, name))).toEqual({ product, byRule });
  });

  it.each<[Ecosystem, string]>([
    ["Maven", "org.springframework.data:spring-data-jpa"],
    ["Maven", "org.webjars:bootstrap"],
    ["Composer", "laravel/sanctum"],
    ["Docker", "myorg/php"],
    ["Docker", "registry.example.com/java-base"],
    ["npm", "left-pad"],
  ])("no match: %s %s", (eco, name) => {
    expect(M.match(dep(eco, name))).toBeNull();
  });
});

describe("osFromTag", () => {
  it.each([
    ["18-alpine3.19", [{ product: "alpine-linux", version: "3.19", display: "3.19" }]],
    ["18-bullseye", [{ product: "debian", version: "11", display: "11 (bullseye)" }]],
    ["3.12-slim-Bookworm", [{ product: "debian", version: "12", display: "12 (bookworm)" }]],
    ["17-jre-jammy", [{ product: "ubuntu", version: "22.04", display: "22.04 (jammy)" }]],
    ["bookworm-slim", [{ product: "debian", version: "12", display: "12 (bookworm)" }]],
    ["8.3-fpm", []],
    ["latest", []],
  ])("%s", (tag, hits) => {
    expect(osFromTag(tag, catalogue()).hits).toEqual(hits);
  });

  it("skips a blank codename", () => {
    const rel = (name: string, eol: string | null, codename: string) => ({
      name,
      releaseDate: "2023-06-10",
      isEol: false,
      eolFrom: eol,
      latest: { name: "1" },
      codename,
    });
    const cat = parseCatalogue({
      result: [
        {
          name: "debian",
          label: "Debian",
          aliases: [],
          identifiers: [],
          releases: [rel("13", null, "  "), rel("12", "2026-06-10", "Bookworm")],
        },
      ],
    });
    expect(osFromTag("12-bookworm", cat).hits).toEqual([
      { product: "debian", version: "12", display: "12 (bookworm)" },
    ]);
  });

  it("reports an unpinned alpine", () => {
    const reading = osFromTag("18-alpine", catalogue());
    expect(reading.hits).toEqual([]);
    expect(reading.missing).toEqual([["alpine-linux", "Alpine version not pinned"]]);
  });
});
