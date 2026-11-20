import { existsSync } from "node:fs";
import { chmod, copyFile, cp, mkdir, mkdtemp, realpath, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { finding } from "../../src/models.js";
import { listFiles, type ScanContext } from "../../src/scan.js";
import { dotnetSource, parseTfm } from "../../src/sources/dotnet.js";
import type { Runner, RunResult } from "../../src/tools.js";

const FIXTURES = join(dirname(fileURLToPath(import.meta.url)), "..", "fixtures");
const BOMS = join(FIXTURES, "boms");

let tmp: string;
let root: string;
let bin: string;
let calls: { cmd: string[]; cwd: string; env: NodeJS.ProcessEnv }[];
let progress: string[];
let hints: string[];

beforeEach(async () => {
  tmp = await realpath(await mkdtemp(join(tmpdir(), "dotnet-")));
  root = join(tmp, "project");
  bin = join(tmp, "bin");
  await mkdir(root);
  await mkdir(bin);
  calls = [];
  progress = [];
  hints = [];
});
afterEach(async () => { await rm(tmp, { recursive: true, force: true }); });

async function install(...names: string[]): Promise<void> {
  for (const name of names) {
    await writeFile(join(bin, name), "#!/bin/sh\n");
    await chmod(join(bin, name), 0o755);
  }
}

async function put(path: string, content = ""): Promise<void> {
  await mkdir(dirname(join(root, path)), { recursive: true });
  await writeFile(join(root, path), content);
}

function sdkProject(inner: string): string {
  return `<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>${inner}</PropertyGroup></Project>`;
}

const msbuildJson = (tf: string, tfs: string, version = ""): string =>
  JSON.stringify({ Properties: { TargetFramework: tf, TargetFrameworks: tfs, TargetFrameworkVersion: version } });

/**
 * Emulates the real commands. dotnet-CycloneDX writes the recorded BOM (recorded from the real
 * tool 6.3.1 on the dotnet-cpm fixture) to --output/--filename; `dotnet msbuild` prints `msbuild`.
 */
function fake(opts: { bom?: string; msbuild?: Partial<RunResult>; tool?: Partial<RunResult> } = {}): Runner {
  return async (cmd, o) => {
    calls.push({ cmd, cwd: o.cwd, env: o.env });
    const ok: RunResult = { code: 0, stdout: "", stderr: "", timedOut: false };
    if (cmd[0]!.endsWith("dotnet-CycloneDX")) {
      const r = { ...ok, ...opts.tool };
      if (r.code === 0 && !r.timedOut) {
        await copyFile(join(BOMS, opts.bom ?? "dotnet-api.json"),
          join(cmd[cmd.indexOf("--output") + 1]!, cmd[cmd.indexOf("--filename") + 1]!));
      }
      return r;
    }
    return { ...ok, stdout: msbuildJson("net8.0", ""), ...opts.msbuild };
  };
}

const never: Runner = async () => { throw new Error("must not run"); };

async function scan(run: Runner, env: NodeJS.ProcessEnv = { PATH: bin }) {
  const ctx: ScanContext = {
    root, env, run, progress: (m) => progress.push(m), hint: (m) => hints.push(m),
  };
  return dotnetSource.scan(await listFiles(root), ctx);
}

describe("parseTfm", () => {
  it.each([
    ["net8.0", [".NET", "8.0"]],
    ["net8.0-windows", [".NET", "8.0"]],
    ["net10.0", [".NET", "10.0"]],
    ["netcoreapp3.1", [".NET", "3.1"]],
    ["net48", [".NET Framework", "4.8"]],
    ["net472", [".NET Framework", "4.7.2"]],
    ["v4.7.2", [".NET Framework", "4.7.2"]],
    ["netstandard2.0", null],
  ])("%s", (tfm, expected) => {
    expect(parseTfm(tfm)).toEqual(expected);
  });
});

describe(".NET source", () => {
  it("reads package references from the tool's BOM", async () => {
    await cp(join(FIXTURES, "projects", "dotnet-cpm"), root, { recursive: true });
    await install("dotnet", "dotnet-CycloneDX");
    const result = await scan(fake());
    expect(result.dependencies.map((d) => [d.ecosystem, d.name, d.version, d.source])).toEqual([
      ["NuGet", "Newtonsoft.Json", "13.0.3", "src/Api/Api.csproj"],
      ["NuGet", "Serilog", "3.1.0", "src/Api/Api.csproj"],
    ]);
    expect(result.findings).toEqual([
      finding(".NET", "8.0.100", "SDK 8.0.100", "global.json"),
      finding(".NET", "8.0", "net8.0", "src/Api/Api.csproj"),
    ]);
    expect(result.unrecognised).toEqual([]);
    const tool = calls.find((c) => c.cmd[0]!.endsWith("dotnet-CycloneDX"))!;
    expect(tool.cmd.slice(1, 4)).toEqual([join(root, "src/Api/Api.csproj"), "--output-format", "Json"]);
    expect(tool.cmd[4]).toBe("--output");
    expect(existsSync(tool.cmd[5]!)).toBe(false); // temp dir removed
    expect(tool.cwd).toBe(join(root, "src/Api"));
    expect(tool.env["PATH"]).toBe(bin);
    expect(progress).toEqual(["Running CycloneDX .NET tool on src/Api/Api.csproj…"]);
  });

  it("asks msbuild for the target framework", async () => {
    await put("Lib.csproj", sdkProject(""));
    await install("dotnet", "dotnet-CycloneDX");
    const result = await scan(fake({ msbuild: { stdout: msbuildJson("", "net8.0;net48") } }));
    expect(result.findings).toEqual([
      finding(".NET", "8.0", "net8.0", "Lib.csproj"),
      finding(".NET Framework", "4.8", "net48", "Lib.csproj"),
    ]);
    const msbuild = calls.find((c) => c.cmd[1] === "msbuild")!;
    expect(msbuild.cmd.slice(2)).toEqual([
      join(root, "Lib.csproj"),
      "-getProperty:TargetFramework", "-getProperty:TargetFrameworks", "-getProperty:TargetFrameworkVersion"]);
    expect(msbuild.cwd).toBe(root);
  });

  it("reads msbuild's JSON after a banner on stdout", async () => {
    // The project file says net6.0; only msbuild (which sees Directory.Build.props) says net8.0.
    await put("Lib.csproj", sdkProject("<TargetFramework>net6.0</TargetFramework>"));
    await install("dotnet", "dotnet-CycloneDX");
    const stdout = `Welcome to .NET 11.0!\n---------------------\nSDK Version: 11.0.100\n${msbuildJson("net8.0", "")}\n`;
    const result = await scan(fake({ msbuild: { stdout } }));
    expect(result.findings).toEqual([finding(".NET", "8.0", "net8.0", "Lib.csproj")]);
  });

  it("tolerates spaces and a trailing semicolon in TargetFrameworks", async () => {
    await put("Lib.csproj", sdkProject(""));
    await install("dotnet", "dotnet-CycloneDX");
    const result = await scan(fake({ msbuild: { stdout: msbuildJson("", "net8.0; net48;") } }));
    expect(result.findings.map((f) => f.display)).toEqual(["net8.0", "net48"]);
    expect(result.unrecognised).toEqual([]);
  });

  it("falls back to the project file when msbuild fails", async () => {
    await put("Lib.csproj", sdkProject("<TargetFramework>net6.0</TargetFramework>"));
    await install("dotnet", "dotnet-CycloneDX");
    const result = await scan(fake({ msbuild: { code: 1, stderr: "boom" } }));
    expect(result.findings).toEqual([finding(".NET", "6.0", "net6.0", "Lib.csproj")]);
    expect(result.unrecognised).toEqual([]);
  });

  it("falls back to the project file when msbuild prints something else", async () => {
    await put("Lib.csproj", sdkProject("<TargetFramework>net6.0</TargetFramework>"));
    await install("dotnet", "dotnet-CycloneDX");
    const result = await scan(fake({ msbuild: { stdout: "not json" } }));
    expect(result.findings).toEqual([finding(".NET", "6.0", "net6.0", "Lib.csproj")]);
  });

  it("reads an old-style namespaced project file without dotnet", async () => {
    await put("Old.csproj",
      '<Project xmlns="http://schemas.microsoft.com/developer/msbuild/2003">' +
      "<PropertyGroup><TargetFrameworkVersion>v4.7.2</TargetFrameworkVersion></PropertyGroup></Project>");
    const result = await scan(never);
    expect(result.findings).toEqual([finding(".NET Framework", "4.7.2", "v4.7.2", "Old.csproj")]);
  });

  it("reports dotnet missing", async () => {
    await put("Lib.csproj", sdkProject("<TargetFramework>net8.0</TargetFramework>"));
    const result = await scan(never);
    expect(result.findings).toEqual([finding(".NET", "8.0", "net8.0", "Lib.csproj")]);
    expect(result.unrecognised).toEqual([{ source: "Lib.csproj", reason: "not scanned (dotnet not found)" }]);
    expect(hints).toEqual([]);
  });

  it("reports the CycloneDX tool missing with an install hint", async () => {
    await put("A/A.csproj", sdkProject("<TargetFramework>net8.0</TargetFramework>"));
    await put("B/B.csproj", sdkProject("<TargetFramework>net8.0</TargetFramework>"));
    await install("dotnet");
    const result = await scan(fake());
    expect(result.unrecognised).toEqual([
      { source: "A/A.csproj", reason: "not scanned (CycloneDX .NET tool not found)" },
      { source: "B/B.csproj", reason: "not scanned (CycloneDX .NET tool not found)" },
    ]);
    expect(hints).toEqual(["Install the CycloneDX .NET tool: dotnet tool install --global CycloneDX --version 6.3.1"]);
  });

  it("skips netstandard targets silently", async () => {
    await put("Lib.csproj", sdkProject("<TargetFramework>netstandard2.0</TargetFramework>"));
    const result = await scan(never);
    expect(result.findings).toEqual([]);
    expect(result.unrecognised.map((u) => u.reason)).toEqual(["not scanned (dotnet not found)"]);
  });

  it("skips netstandard among several targets", async () => {
    await put("Lib.csproj", sdkProject("<TargetFrameworks>net8.0;net48;netstandard2.0</TargetFrameworks>"));
    const result = await scan(never);
    expect(result.findings.map((f) => f.display)).toEqual(["net8.0", "net48"]);
  });

  it("reports a project with no readable target framework", async () => {
    await put("Api.csproj", '<Project Sdk="Microsoft.NET.Sdk"></Project>');
    const result = await scan(never);
    expect(result.unrecognised[0]).toEqual({ source: "Api.csproj", reason: "couldn't read the .NET target framework" });
  });

  it("reports an unrecognised target framework", async () => {
    await put("Api.csproj", sdkProject("<TargetFramework>uap10.0</TargetFramework>"));
    const result = await scan(never);
    expect(result.unrecognised[0]).toEqual({ source: "Api.csproj", reason: "couldn't read the .NET target framework" });
  });

  it("reports a tool failure for one project and still scans the next", async () => {
    await put("A/A.csproj", sdkProject("<TargetFramework>net8.0</TargetFramework>"));
    await put("B/B.csproj", sdkProject("<TargetFramework>net8.0</TargetFramework>"));
    await install("dotnet", "dotnet-CycloneDX");
    const base = fake();
    let n = 0;
    const run: Runner = async (cmd, o) => {
      if (cmd[0]!.endsWith("dotnet-CycloneDX") && ++n === 1) {
        return { code: 1, stdout: "", stderr: "\nrestore failed\n", timedOut: false };
      }
      return base(cmd, o);
    };
    const result = await scan(run);
    expect(result.unrecognised).toEqual([
      { source: "A/A.csproj", reason: "not scanned (CycloneDX .NET tool failed: restore failed)" }]);
    expect(result.findings).toHaveLength(2);
    expect(result.dependencies.map((d) => d.source)).toEqual(["B/B.csproj", "B/B.csproj"]);
  });

  it("reports a timeout", async () => {
    await put("A.csproj", sdkProject("<TargetFramework>net8.0</TargetFramework>"));
    await install("dotnet", "dotnet-CycloneDX");
    const result = await scan(fake({ tool: { code: null, timedOut: true } }));
    expect(result.unrecognised).toEqual([{ source: "A.csproj", reason: "not scanned (CycloneDX .NET tool timed out)" }]);
  });

  it("reads the SDK version from global.json", async () => {
    await put("global.json", JSON.stringify({ sdk: { version: "8.0.100" } }));
    const result = await scan(never);
    expect(result.findings).toEqual([finding(".NET", "8.0.100", "SDK 8.0.100", "global.json")]);
  });

  it("ignores a global.json without an sdk version", async () => {
    await put("global.json", JSON.stringify({ "msbuild-sdks": {} }));
    const result = await scan(never);
    expect(result.findings).toEqual([]);
    expect(result.unrecognised).toEqual([]);
  });

  it("reports an unreadable SDK version and a broken global.json", async () => {
    await put("global.json", JSON.stringify({ sdk: { version: "latest" } }));
    await put("sub/global.json", "{");
    const result = await scan(never);
    expect(result.unrecognised).toEqual([
      { source: "global.json", reason: "couldn't read the .NET SDK version" },
      { source: "sub/global.json", reason: "couldn't parse global.json" },
    ]);
  });
});
