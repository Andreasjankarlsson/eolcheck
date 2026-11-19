import { chmod, mkdir, mkdtemp, readFile, realpath, rm, writeFile } from "node:fs/promises";
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

  it("passes shell metacharacters verbatim", async () => {
    const r = await runProcess([process.execPath, "-e", "console.log(process.argv[1])", "a;b $HOME `x` | y"], { cwd: tmp, env: process.env });
    expect(r.stdout).toBe("a;b $HOME `x` | y\n");
  });

  it("uses the env and cwd it is given", async () => {
    const r = await runProcess(
      [process.execPath, "-e", "console.log(process.env.EOLC_X, process.env.HOME, process.cwd())"],
      { cwd: tmp, env: { PATH: process.env.PATH, EOLC_X: "yes" } },
    );
    const [x, home, cwd] = r.stdout.trim().split(" ");
    expect(x).toBe("yes");
    expect(home).toBe("undefined");
    expect(await realpath(cwd!)).toBe(await realpath(tmp));
  });

  it("times out and kills a grandchild holding the pipes", async () => {
    const pidFile = join(tmp, "pid");
    const parent = `
      const { spawn } = require("node:child_process");
      const c = spawn(process.execPath, ["-e", "setTimeout(()=>{}, 60000)"], { stdio: "inherit" });
      require("node:fs").writeFileSync(${JSON.stringify(pidFile)}, String(c.pid));
      setTimeout(() => {}, 60000);`;
    const t = Date.now();
    const r = await runProcess([process.execPath, "-e", parent], { cwd: tmp, env: process.env, timeoutMs: 500 });
    expect(r.timedOut).toBe(true);
    expect(Date.now() - t).toBeLessThan(2000);
    const pid = Number(await readFile(pidFile, "utf8"));
    let alive = true;
    for (let i = 0; i < 20 && alive; i++) {
      try { process.kill(pid, 0); await new Promise((res) => setTimeout(res, 50)); } catch { alive = false; }
    }
    expect(alive).toBe(false);
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
