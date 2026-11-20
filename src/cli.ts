#!/usr/bin/env node
/** Command-line entry point: eolchecker <folder>. The only module that prints or exits. */
import { realpathSync } from "node:fs";
import { stat } from "node:fs/promises";
import { homedir } from "node:os";
import { basename, extname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";
import { ApiUnavailable, renderTable, scan as defaultScan, writeSbom, type Report } from "./index.js";

const USAGE = `Usage: eolchecker <path> [--sbom FILE] [--json]

Check whether a repo's dependencies are past end-of-life.

Arguments:
  path           folder of a cloned repo

Options:
  --sbom FILE    also write every detected dependency to FILE (.csv or .md)
  --json         print the report as JSON instead of a table
  -h, --help     show this help
`;

export interface Deps {
  scan?: typeof defaultScan;
  stdout?: (s: string) => void;
  stderr?: (s: string) => void;
  isTTY?: boolean;
}

function expandUser(p: string): string {
  return p === "~" || p.startsWith("~/") ? homedir() + p.slice(1) : p;
}

/** "ENOENT: no such file or directory, open 'x'" -> "no such file or directory". */
function reason(err: unknown): string {
  const msg = err instanceof Error ? err.message : String(err);
  return msg.replace(/^[A-Z0-9_]+: /, "").replace(/, \w+ '.*$/, "");
}

export async function main(argv: string[], deps: Deps = {}): Promise<number> {
  const scan = deps.scan ?? defaultScan;
  const stdout = deps.stdout ?? ((s: string) => void process.stdout.write(s));
  const stderr = deps.stderr ?? ((s: string) => void process.stderr.write(s));
  const isTTY = deps.isTTY ?? Boolean(process.stdout.isTTY);

  let values: { sbom?: string; json?: boolean; help?: boolean };
  let positionals: string[];
  try {
    ({ values, positionals } = parseArgs({
      args: argv,
      allowPositionals: true,
      options: {
        sbom: { type: "string" },
        json: { type: "boolean" },
        help: { type: "boolean", short: "h" },
      },
    }));
  } catch (err) {
    stderr(`${USAGE}\n${reason(err)}\n`);
    return 2;
  }
  if (values.help) {
    stdout(USAGE);
    return 0;
  }
  if (positionals.length !== 1) {
    stderr(`${USAGE}\neolchecker: expected exactly one path\n`);
    return 2;
  }

  const sbomPath = values.sbom !== undefined ? resolve(expandUser(values.sbom)) : undefined;
  if (sbomPath !== undefined && ![".csv", ".md"].includes(extname(sbomPath).toLowerCase())) {
    stderr("--sbom file must end in .csv or .md\n");
    return 2;
  }

  const typed = positionals[0];
  const root = resolve(expandUser(typed));
  let info;
  try {
    info = await stat(root);
  } catch {
    stderr(`Path not found: ${typed}\n`);
    return 2;
  }
  if (!info.isDirectory()) {
    stderr(`Not a folder: ${typed}\n`);
    return 2;
  }

  // Tools run detached, so Ctrl+C never reaches them; abort tells scan to kill them and clean up.
  const controller = new AbortController();
  const onSignal = (): void => controller.abort();
  process.on("SIGINT", onSignal);
  process.on("SIGTERM", onSignal);
  let report: Report;
  try {
    report = await scan(root, {
      env: process.env,
      onProgress: (m) => stderr(`${m}\n`),
      warn: (m) => stderr(`${m}\n`),
      signal: controller.signal,
    });
  } catch (err) {
    if (controller.signal.aborted) {
      stderr("Cancelled.\n");
      return 130;
    }
    if (err instanceof ApiUnavailable) {
      stderr(`Couldn't fetch end-of-life dates from endoflife.date: ${err.message}\n`);
      return 1;
    }
    stderr(`eolchecker: unexpected error: ${err instanceof Error ? err.message : String(err)}\n`);
    return 1;
  } finally {
    process.off("SIGINT", onSignal);
    process.off("SIGTERM", onSignal);
  }

  const nothing = !report.rows.length && !report.sbom.length && !report.unrecognised.length;
  if (values.json) {
    stdout(JSON.stringify(report, null, 2) + "\n");
  } else if (nothing) {
    stdout(`No dependencies found in ${root}\n`);
  } else {
    stdout(renderTable(basename(root) || root, report, { color: isTTY }) + "\n");
  }

  if (sbomPath === undefined) return 0;
  try {
    await writeSbom(sbomPath, report.sbom);
  } catch (err) {
    stderr(`Couldn't write ${sbomPath}: ${reason(err)}\n`);
    return 1;
  }
  // Keep stdout valid JSON in --json mode.
  (values.json ? stderr : stdout)(`SBOM written to ${sbomPath}\n`);
  return 0;
}

function isEntryModule(): boolean {
  const entry = process.argv[1];
  if (!entry) return false;
  try {
    return realpathSync(entry) === realpathSync(fileURLToPath(import.meta.url));
  } catch {
    return false;
  }
}

if (isEntryModule()) {
  // Set exitCode and let Node exit on its own: a hard exit can truncate piped stdout.
  process.exitCode = await main(process.argv.slice(2));
}
