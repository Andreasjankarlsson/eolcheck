/** Render the results as a plain-text table (returns a string; never prints). */
import { styleText } from "node:util";
import type { Report } from "../rows.js";

const STATUS_STYLE: Record<string, Parameters<typeof styleText>[0]> = {
  "END OF LIFE": ["bold", "red"],
  supported: "green",
  "no EOL date": "yellow",
  "version not found": "dim",
};

const COLUMNS = ["Component", "Version", "Found in", "End of support", "Latest", "Status"];

export function renderTable(repoName: string, report: Report, opts: { color: boolean }): string {
  const paint = (format: Parameters<typeof styleText>[0], text: string) =>
    opts.color ? styleText(format, text, { validateStream: false }) : text;

  const out: string[] = ["", paint("bold", repoName)];
  if (report.rows.length > 0) {
    const body = report.rows.map((r) => [r.component, r.version, r.foundIn, r.endOfSupport, r.latest, r.status]);
    const widths = COLUMNS.map((c, i) => Math.max(c.length, ...body.map((line) => line[i].length)));
    const line = (values: string[], style: (i: number, padded: string) => string) =>
      values
        .map((v, i) => style(i, i === values.length - 1 ? v : v.padEnd(widths[i])))
        .join("  ")
        .trimEnd();
    out.push(line(COLUMNS, (_, text) => paint("bold", text)));
    for (const values of body) {
      out.push(
        line(values, (i, text) => {
          const format = i === values.length - 1 ? STATUS_STYLE[values[i]] : undefined;
          return format ? paint(format, text) : text;
        }),
      );
    }
  } else {
    out.push("No dependencies tracked by endoflife.date found.");
  }
  if (report.unrecognised.length > 0) {
    out.push("", "Not recognised:");
    const sorted = [...report.unrecognised].sort((a, b) => (a.source < b.source ? -1 : a.source > b.source ? 1 : 0));
    for (const u of sorted) out.push(`  ${u.source}: ${u.reason}`);
  }
  out.push(...report.hints);
  out.push("");
  return out.join("\n");
}
