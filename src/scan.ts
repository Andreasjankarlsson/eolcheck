/** List a folder's files once and run every source on them. */

import type { Dirent } from "node:fs";
import { readdir, stat } from "node:fs/promises";
import { join } from "node:path";
import { rel } from "./util.js";
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

async function isFileLike(dir: string, e: Dirent): Promise<boolean> {
  if (e.isFile()) return true;
  if (!e.isSymbolicLink()) return false;
  try {
    return (await stat(join(dir, e.name))).isFile();
  } catch {
    return false; // broken link
  }
}

/**
 * Absolute file paths under root, skipping SKIP_DIRS and not following folder symlinks
 * (symlinked files are included). Each folder's files come before its subfolders, both sorted.
 * A subfolder that can't be read is skipped and passed to `onUnreadable` (relative POSIX path);
 * an unreadable root throws.
 */
export async function listFiles(root: string, onUnreadable?: (relPath: string) => void): Promise<string[]> {
  const out: string[] = [];
  const walk = async (dir: string): Promise<void> => {
    let entries: Dirent[];
    try {
      entries = await readdir(dir, { withFileTypes: true });
    } catch (err) {
      if (dir === root) throw err;
      onUnreadable?.(rel(root, dir));
      return;
    }
    const byName = (a: { name: string }, b: { name: string }): number => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0);
    const fileEntries: Dirent[] = [];
    for (const e of entries) if (await isFileLike(dir, e)) fileEntries.push(e);
    for (const e of fileEntries.sort(byName)) out.push(join(dir, e.name));
    for (const e of entries.filter((e) => e.isDirectory() && !SKIP_DIRS.has(e.name)).sort(byName)) {
      await walk(join(dir, e.name));
    }
  };
  await walk(root);
  return out;
}

export async function detect(root: string, ctx: ScanContext, sources: Source[]): Promise<DetectResult> {
  const unreadable: string[] = [];
  const files = await listFiles(root, (p) => unreadable.push(p));
  const result = emptyResult();
  for (const p of unreadable) result.unrecognised.push({ source: p, reason: "couldn't read folder" });
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
