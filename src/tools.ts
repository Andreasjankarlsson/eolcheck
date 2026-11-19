import { spawn } from "node:child_process";
import { constants } from "node:fs";
import { access, stat } from "node:fs/promises";
import { delimiter, join } from "node:path";
import { dirsUp } from "./util.js";

export interface RunResult { code: number | null; stdout: string; stderr: string; timedOut: boolean }
export type Runner = (
  cmd: string[],
  opts: { cwd: string; env: NodeJS.ProcessEnv; signal?: AbortSignal; timeoutMs?: number },
) => Promise<RunResult>;

const DEFAULT_TIMEOUT_MS = 180_000;

function abortError(signal: AbortSignal): unknown {
  if (signal.reason !== undefined) return signal.reason;
  const e = new Error("The operation was aborted");
  e.name = "AbortError";
  return e;
}

export const runProcess: Runner = (cmd, opts) =>
  new Promise<RunResult>((resolve, reject) => {
    const { signal } = opts;
    if (signal?.aborted) { reject(abortError(signal)); return; }
    const child = spawn(cmd[0]!, cmd.slice(1), {
      cwd: opts.cwd, env: opts.env, shell: false, stdio: ["ignore", "pipe", "pipe"], detached: true,
    });
    // Kill the whole process group so grandchildren (mvnw -> java) die too.
    const killTree = (): void => {
      try {
        if (child.pid !== undefined) process.kill(-child.pid, "SIGKILL");
      } catch {
        try { child.kill("SIGKILL"); } catch { /* already gone */ }
      }
    };
    let stdout = "";
    let stderr = "";
    let settled = false;
    child.stdout.setEncoding("utf8").on("data", (d: string) => { stdout += d; });
    child.stderr.setEncoding("utf8").on("data", (d: string) => { stderr += d; });

    const onAbort = (): void => {
      killTree();
      finish(() => reject(abortError(signal!)));
    };
    const timer = setTimeout(() => {
      killTree();
      finish(() => resolve({ code: null, stdout, stderr, timedOut: true }));
    }, opts.timeoutMs ?? DEFAULT_TIMEOUT_MS);
    const finish = (fn: () => void): void => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      signal?.removeEventListener("abort", onAbort);
      child.stdout.destroy();
      child.stderr.destroy();
      fn();
    };
    signal?.addEventListener("abort", onAbort, { once: true });

    child.on("error", (err: NodeJS.ErrnoException) => {
      if (err.code === "ENOENT") finish(() => resolve({ code: null, stdout: "", stderr: "not found", timedOut: false }));
      else finish(() => reject(err));
    });
    child.on("close", (code) => finish(() => resolve({ code, stdout, stderr, timedOut: false })));
  });

async function isExecutableFile(p: string): Promise<boolean> {
  try {
    if (!(await stat(p)).isFile()) return false;
    await access(p, constants.X_OK);
    return true;
  } catch {
    return false;
  }
}

export async function findTool(name: string, env: NodeJS.ProcessEnv): Promise<string | null> {
  for (const dir of (env.PATH ?? "").split(delimiter)) {
    if (!dir) continue;
    const candidate = join(dir, name);
    if (await isExecutableFile(candidate)) return candidate;
  }
  return null;
}

/** The nearest executable mvnw from pomDir up to root, else mvn on PATH. */
export async function findMaven(pomDir: string, root: string, env: NodeJS.ProcessEnv): Promise<string[] | null> {
  for (const d of dirsUp(pomDir, root)) {
    const wrapper = join(d, "mvnw");
    if (await isExecutableFile(wrapper)) return [wrapper];
  }
  const mvn = await findTool("mvn", env);
  return mvn ? [mvn] : null;
}

export function describeFailure(tool: string, r: RunResult): string {
  if (r.timedOut) return `not scanned (${tool} timed out)`;
  const line = r.stderr.split("\n").map((l) => l.trim()).find((l) => l !== "");
  return `not scanned (${tool} failed: ${line ?? `exit code ${r.code}`})`;
}
