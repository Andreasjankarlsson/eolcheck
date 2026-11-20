import { readFile } from "node:fs/promises";
import { dirname, isAbsolute, relative, resolve, sep } from "node:path";

/** Directories from `start` up to `root`, both inclusive. Just `[start]` when start is outside root. */
export function dirsUp(start: string, root: string): string[] {
  const top = resolve(root);
  let cur = resolve(start);
  const inside = cur === top || (!isAbsolute(relative(top, cur)) && !relative(top, cur).startsWith(".."));
  if (!inside) return [start];
  const out: string[] = [];
  for (;;) {
    out.push(cur);
    if (cur === top) break;
    cur = dirname(cur);
  }
  return out;
}

/** Reads a file as UTF-8, stripping a leading BOM. */
export async function readText(path: string): Promise<string> {
  const text = await readFile(path, "utf8");
  return text.charCodeAt(0) === 0xfeff ? text.slice(1) : text;
}

/** Path of `path` relative to `root`, with POSIX separators. */
export function rel(root: string, path: string): string {
  return relative(root, path).split(sep).join("/");
}
