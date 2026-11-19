/** List a folder's files once and run every source on them. */

import { readdir } from "node:fs/promises";
import { join } from "node:path";
import { emptyResult, merge, type DetectResult, type Unrecognised } from "./models.js";
import type { Runner } from "./tools.js";

export const SKIP_DIRS: ReadonlySet<string> = new Set([
  ".git", "node_modules", "vendor", "target", "build", "dist", "bin", "obj", ".idea", ".venv",
]);

export interface ScanContext {
  root: string;
  env: NodeJS.ProcessEnv;
  run: Runner;
  signal?: AbortSignal;
  progress: (msg: string) => void;
  hint: (msg: string) => void;
}

export interface Source {
  name: string;
  scan(files: string[], ctx: ScanContext): Promise<DetectResult>;
}

/** Absolute file paths under root, skipping SKIP_DIRS and not following symlinks. Each folder's files come before its subfolders, both sorted. */
export async function listFiles(root: string): Promise<string[]> {
  const out: string[] = [];
  const walk = async (dir: string): Promise<void> => {
    const entries = await readdir(dir, { withFileTypes: true });
    const byName = (a: { name: string }, b: { name: string }): number => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0);
    for (const e of entries.filter((e) => e.isFile()).sort(byName)) out.push(join(dir, e.name));
    for (const e of entries.filter((e) => e.isDirectory() && !SKIP_DIRS.has(e.name)).sort(byName)) {
      await walk(join(dir, e.name));
    }
  };
  await walk(root);
  return out;
}

export async function detect(root: string, ctx: ScanContext, sources: Source[]): Promise<DetectResult> {
  const files = await listFiles(root);
  const result = emptyResult();
  for (const source of sources) {
    try {
      merge(result, await source.scan(files, ctx));
    } catch (err) {
      if (ctx.signal?.aborted) throw err;
      result.unrecognised.push({ source: ".", reason: `couldn't scan with ${source.name}` });
    }
  }
  // The same gap can come from several places; list it once.
  const seen = new Set<string>();
  result.unrecognised = result.unrecognised.filter((u: Unrecognised) => {
    const key = `${u.source}\u0000${u.reason}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
  return result;
}
