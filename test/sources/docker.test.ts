import { mkdir, mkdtemp, realpath, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { ScanContext } from "../../src/scan.js";
import { dockerSource, splitImage } from "../../src/sources/docker.js";

let root: string;

beforeEach(async () => {
  root = await realpath(await mkdtemp(join(tmpdir(), "docker-")));
});
afterEach(async () => {
  await rm(root, { recursive: true, force: true });
});

async function run(files: Record<string, string>) {
  const paths: string[] = [];
  for (const [name, content] of Object.entries(files)) {
    const path = join(root, name);
    await mkdir(dirname(path), { recursive: true });
    await writeFile(path, content);
    paths.push(path);
  }
  return dockerSource.scan(paths, { root } as unknown as ScanContext);
}

describe("file selection", () => {
  it.each([
    ["Dockerfile", true], ["Dockerfile.prod", true], ["api.Dockerfile", true],
    ["web.dockerfile", true], ["docker-compose.yml", true], ["docker-compose.override.yaml", true],
    ["compose.yaml", true], ["compose.dev.yml", true], ["Dockerfile.md", true],
    ["docker-compose-prod.yml", true], ["compose-dev.yaml", true],
    ["README.md", false], ["composer.json", false], ["composer.lock", false],
  ])("%s -> %s", async (name, ok) => {
    const isCompose = /^(docker-)?compose.*\.ya?ml$/.test(name);
    const content = isCompose ? "services:\n  a:\n    image: node:18\n" : "FROM node:18\n";
    const result = await run({ [name]: content });
    expect(result.dependencies.length).toBe(ok ? 1 : 0);
  });
});

describe("Dockerfile", () => {
  it("reads a FROM line", async () => {
    const r = await run({ Dockerfile: "FROM node:18-alpine3.19\n" });
    expect(r.dependencies).toEqual([
      { ecosystem: "Docker", name: "node", version: "18", display: "18-alpine3.19", source: "Dockerfile", tag: "18-alpine3.19" },
    ]);
  });

  it("handles multi-stage, platform flag and ARG", async () => {
    const r = await run({
      Dockerfile: "ARG NODE=18\nFROM --platform=$BUILDPLATFORM node:${NODE}-bullseye AS build\nRUN x\nFROM build\nFROM scratch\n",
    });
    expect(r.dependencies.length).toBe(1);
    const dep = r.dependencies[0]!;
    expect([dep.name, dep.version, dep.tag]).toEqual(["node", "18", "18-bullseye"]);
  });

  it.each([
    ["FROM node", "latest", "image tag doesn't pin a version"],
    ["FROM node:latest", "latest", "image tag doesn't pin a version"],
    ["FROM node:lts-slim", "lts-slim", "image tag doesn't pin a version"],
    ["FROM node@sha256:abc", "sha256:abc", "image pinned by digest only"],
    ["FROM node:${V}", "${V}", "image tag set by a build variable"],
  ])("unpinned: %s", async (line, display, missing) => {
    const r = await run({ Dockerfile: line + "\n" });
    const dep = r.dependencies[0]!;
    expect(dep.version).toBeNull();
    expect([dep.display, dep.missing]).toEqual([display, missing]);
    expect(dep.tag).toBe(line === "FROM node" || line === "FROM node@sha256:abc" ? undefined : display);
  });

  it("uses the tag when a digest is also present", async () => {
    const r = await run({ Dockerfile: "FROM node:18@sha256:abc\n" });
    const dep = r.dependencies[0]!;
    expect([dep.name, dep.version, dep.tag]).toEqual(["node", "18", "18"]);
  });

  it("keeps a codename tag unpinned", async () => {
    const r = await run({ Dockerfile: "FROM debian:bookworm-slim\n" });
    const dep = r.dependencies[0]!;
    expect([dep.version, dep.tag, dep.missing]).toEqual([null, "bookworm-slim", "image tag doesn't pin a version"]);
  });

  it("joins continuation lines", async () => {
    const r = await run({ Dockerfile: "FROM \\\n  node:18\n" });
    expect([r.dependencies[0]!.name, r.dependencies[0]!.version]).toEqual(["node", "18"]);
  });

  it("accepts lowercase from and alias case-insensitively", async () => {
    const r = await run({ Dockerfile: "from node:20 as Build\nFROM build\n" });
    expect(r.dependencies.map((d) => d.name)).toEqual(["node"]);
  });

  it("reports a variable in the image name as unrecognised", async () => {
    const r = await run({ Dockerfile: "FROM ${BASE}:1\n" });
    expect(r.dependencies).toEqual([]);
    expect(r.unrecognised).toEqual([{ source: "Dockerfile", reason: "couldn't read the image name in FROM ${BASE}:1" }]);
  });

  it("keeps the first ARG default", async () => {
    const r = await run({ Dockerfile: "ARG V=18\nARG V=20\nFROM node:$V\n" });
    expect(r.dependencies[0]!.version).toBe("18");
  });
});

describe("compose", () => {
  it("reads images and substitutes defaults", async () => {
    const r = await run({
      "docker-compose.yml":
        "services:\n  db:\n    image: \"postgres:16\"\n" +
        "  web:\n    image: \"${REG:-ghcr.io/acme}/web:${TAG:-1.4}\"\n" +
        "  app:\n    build: .\n",
    });
    expect(r.dependencies.map((d) => [d.name, d.version])).toEqual([["postgres", "16"], ["ghcr.io/acme/web", "1.4"]]);
  });

  it("reads dashed file names", async () => {
    const r = await run({ "docker-compose-prod.yml": "services:\n  db:\n    image: postgres:16\n" });
    expect(r.dependencies.map((d) => [d.name, d.version])).toEqual([["postgres", "16"]]);
  });

  it("flags a variable without a default", async () => {
    const r = await run({ "compose.yaml": "services:\n  a:\n    image: \"node:${TAG}\"\n" });
    expect(r.dependencies[0]!.missing).toBe("image tag set by a variable");
  });

  it("reports a broken file as unrecognised", async () => {
    const r = await run({ "compose.yml": ": :\n" });
    expect(r.unrecognised).toEqual([{ source: "compose.yml", reason: "couldn't parse compose.yml" }]);
  });
});

describe("splitImage", () => {
  it("does not treat a registry port as a tag", () => {
    expect(splitImage("localhost:5000/app:1.2")).toEqual(["localhost:5000/app", "1.2", null]);
    expect(splitImage("localhost:5000/app")).toEqual(["localhost:5000/app", null, null]);
    expect(splitImage("node@sha256:abc")).toEqual(["node", null, "sha256:abc"]);
  });
});
