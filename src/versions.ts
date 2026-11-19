/** Helpers for making sense of version text found in build files. */

const NUMERIC = /\d+(?:\.\d+)*/;
const NUMERIC_AT_START = /^\d+(?:\.\d+)*/;
const RANGE_MARKERS = /[\^~<>|*\s]|\.x\b|\.X\b|^x$/;

/** 'v6.4.1' -> '6.4.1', '6.4.1.Final' -> '6.4.1', 'latest' -> null. */
export function normalise(raw: string): string | null {
  const text = raw.trim().replace(/^[vV]+/, "");
  const m = NUMERIC_AT_START.exec(text);
  return m ? m[0] : null;
}

export function isRange(raw: string): boolean {
  return RANGE_MARKERS.test(raw.trim());
}

function compare(a: number[], b: number[]): number {
  for (let i = 0; i < Math.min(a.length, b.length); i++) {
    if (a[i] !== b[i]) return a[i]! - b[i]!;
  }
  return a.length - b.length;
}

/** Lowest version a range allows; null when no version can be read. */
export function lowest(raw: string): string | null {
  const text = raw.trim();
  if (!text || text.includes(":") || text.includes("/")) return null;
  let best: number[] | null = null;
  let bestText: string | null = null;
  for (const alt of text.split(/\|\|?/)) {
    if (alt.trim().startsWith("<")) continue; // only an upper limit: says nothing about the lowest
    const m = NUMERIC.exec(alt);
    if (!m) continue;
    const key = m[0].split(".").map(Number);
    if (best === null || compare(key, best) < 0) {
      best = key;
      bestText = m[0];
    }
  }
  return bestText;
}

/** '4.7.2' -> ['4.7.2', '4.7', '4']. */
export function cycleCandidates(version: string): string[] {
  const parts = version.split(".");
  const out: string[] = [];
  for (let i = parts.length; i > 0; i--) {
    const c = parts.slice(0, i).join(".");
    if (!out.includes(c)) out.push(c);
  }
  return out;
}
