/** Public library API. Never prints; messages go to the callbacks. */

import { join } from "node:path";
import { defaultCacheDir, loadCatalogue, type Catalogue } from "./catalogue.js";
import { buildReport, type Report } from "./rows.js";
import { detect, type ScanContext, type Source } from "./scan.js";
import { composerSource } from "./sources/composer.js";
import { dockerSource } from "./sources/docker.js";
import { dotnetSource } from "./sources/dotnet.js";
import { mavenSource } from "./sources/maven.js";
import { npmSource } from "./sources/npm.js";
import { runProcess, type Runner } from "./tools.js";

export type { Report, Row, SbomRow } from "./rows.js";
export type { Unrecognised } from "./models.js";
export { ApiUnavailable } from "./catalogue.js";
export { writeSbom } from "./output/sbom.js";
export { renderTable } from "./output/table.js";

export interface ScanOptions {
  cacheDir?: string;
  env?: NodeJS.ProcessEnv;
  onProgress?: (msg: string) => void;
  warn?: (msg: string) => void;
  signal?: AbortSignal;
  runner?: Runner;
  catalogue?: () => Promise<Catalogue>;
}

const SOURCES: Source[] = [mavenSource, npmSource, dotnetSource, composerSource, dockerSource];

export async function scan(root: string, options: ScanOptions = {}): Promise<Report> {
  const env = options.env ?? process.env;
  const hints: string[] = [];
  const ctx: ScanContext = {
    root,
    env,
    run: options.runner ?? runProcess,
    signal: options.signal,
    progress: options.onProgress ?? (() => {}),
    hint: (msg) => {
      if (!hints.includes(msg)) hints.push(msg);
    },
  };
  const result = await detect(root, ctx, SOURCES);
  if (!result.findings.length && !result.dependencies.length && !result.unrecognised.length) {
    return { rows: [], sbom: [], unrecognised: [], hints: [] };
  }
  const catalogue =
    options.catalogue ??
    (() =>
      loadCatalogue({
        cacheFile: join(options.cacheDir ?? defaultCacheDir(env), "products-full.json"),
        warn: options.warn,
      }));
  return buildReport(result, await catalogue(), hints);
}
