import { chmod, mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { describeFailure, findMaven, findTool, runProcess } from "../src/tools.js";

let tmp: string;
beforeEach(async () => { tmp = await mkdtemp(join(tmpdir(), "tools-")); });
afterEach(async () => { await rm(tmp, { recursive: true, force: true }); });

async function script(path: string, mode: number): Promise<void> {
  await mkdir(dirname(path), { recursive: true });
  await writeFile(path, "#!/bin/sh\n");
  await chmod(path, mode);
}

describe("tools", () => {
  it("finds a tool only on the PATH it is given", async () => {
    await script(join(tmp, "fake-mvn"), 0o755);
    expect(await findTool("fake-mvn", { PATH: tmp })).toBe(join(tmp, "fake-mvn"));
    expect(await findTool("fake-mvn", { PATH: "/usr/bin" })).toBeNull();
  });

  it("prefers the nearest executable mvnw", async () => {
    await script(join(tmp, "mvnw"), 0o755);
    await script(join(tmp, "a", "mvnw"), 0o755);
    await mkdir(join(tmp, "a", "b"), { recursive: true });
    expect(await findMaven(join(tmp, "a", "b"), tmp, { PATH: "" })).toEqual([join(tmp, "a", "mvnw")]);
    await chmod(join(tmp, "a", "mvnw"), 0o644);
    expect(await findMaven(join(tmp, "a", "b"), tmp, { PATH: "" })).toEqual([join(tmp, "mvnw")]);
  });

  it("falls back to mvn on PATH, else null", async () => {
    const bin = join(tmp, "bin");
    await script(join(bin, "mvn"), 0o755);
    expect(await findMaven(tmp, tmp, { PATH: bin })).toEqual([join(bin, "mvn")]);
    expect(await findMaven(tmp, tmp, { PATH: "" })).toBeNull();
  });

  it("times out a hanging process", async () => {
    const t = Date.now();
    const r = await runProcess([process.execPath, "-e", "setTimeout(()=>{}, 60000)"], { cwd: tmp, env: process.env, timeoutMs: 200 });
    expect(r.timedOut).toBe(true);
    expect(Date.now() - t).toBeLessThan(2000);
  });

  it("passes arguments with spaces untouched", async () => {
    const r = await runProcess([process.execPath, "-e", "console.log(process.argv[1])", "a b"], { cwd: tmp, env: process.env });
    expect(r.stdout).toBe("a b\n");
    expect(r.code).toBe(0);
  });

  it("reports a missing executable", async () => {
    const r = await runProcess([join(tmp, "nope")], { cwd: tmp, env: process.env });
    expect(r).toEqual({ code: null, stdout: "", stderr: "not found", timedOut: false });
  });

  it("rejects when aborted", async () => {
    const ac = new AbortController();
    const p = runProcess([process.execPath, "-e", "setTimeout(()=>{}, 60000)"], { cwd: tmp, env: process.env, signal: ac.signal });
    setTimeout(() => ac.abort(), 100);
    await expect(p).rejects.toMatchObject({ name: "AbortError" });
  });

  it("describes failures", () => {
    expect(describeFailure("Maven", { code: 1, stderr: "\n[ERROR] boom\nmore", stdout: "", timedOut: false }))
      .toBe("not scanned (Maven failed: [ERROR] boom)");
    expect(describeFailure("Maven", { code: 3, stderr: "  \n", stdout: "", timedOut: false }))
      .toBe("not scanned (Maven failed: exit code 3)");
    expect(describeFailure("Maven", { code: null, stderr: "", stdout: "", timedOut: true }))
      .toBe("not scanned (Maven timed out)");
  });
});
