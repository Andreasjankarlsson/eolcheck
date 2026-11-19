/** Render SBOM rows as CSV or a Markdown table. */
import { writeFile } from "node:fs/promises";
import { extname } from "node:path";
import type { SbomRow } from "../rows.js";

const HEADER = ["Ecosystem", "Name", "Version", "Found in", "Product", "End of support", "Status"];

function cells(row: SbomRow): string[] {
  return [row.ecosystem, row.name, row.version, row.foundIn, row.product, row.endOfSupport, row.status];
}

function csvField(value: string): string {
  return /[,"\r\n]/.test(value) ? `"${value.replaceAll('"', '""')}"` : value;
}

export function toCsv(rows: SbomRow[]): string {
  return [HEADER, ...rows.map(cells)].map((line) => line.map(csvField).join(",") + "\n").join("");
}

function mdLine(values: string[]): string {
  return "| " + values.map((c) => c.replaceAll("|", "\\|")).join(" | ") + " |";
}

export function toMarkdown(rows: SbomRow[]): string {
  const lines = [mdLine(HEADER), "|" + "---|".repeat(HEADER.length), ...rows.map((r) => mdLine(cells(r)))];
  return lines.join("\n") + "\n";
}

/** Write the SBOM; the format follows the file extension (.csv or .md). */
export async function writeSbom(path: string, rows: SbomRow[]): Promise<void> {
  const ext = extname(path).toLowerCase();
  if (ext !== ".csv" && ext !== ".md") {
    throw new Error(`Unsupported SBOM file type '${extname(path)}'; use .csv or .md`);
  }
  await writeFile(path, ext === ".csv" ? toCsv(rows) : toMarkdown(rows), "utf8");
}
