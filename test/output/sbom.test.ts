import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { toCsv, toMarkdown, writeSbom } from "../../src/output/sbom.js";
import type { SbomRow } from "../../src/rows.js";

const ROW: SbomRow = {
  ecosystem: "npm",
  name: "react",
  version: "^18.2.0",
  foundIn: "web/package.json",
  product: "React",
  endOfSupport: "",
  status: "no EOL date",
};
const blank = (over: Partial<SbomRow>): SbomRow => ({
  ecosystem: "npm", name: "x", version: "1", foundIn: "p.json", product: "", endOfSupport: "", status: "", ...over,
});

describe("sbom", () => {
  it("csv", () => {
    expect(toCsv([ROW])).toBe(
      "Ecosystem,Name,Version,Found in,Product,End of support,Status\n" +
        "npm,react,^18.2.0,web/package.json,React,,no EOL date\n",
    );
  });
  it("csv quotes commas, quotes and newlines", () => {
    const out = toCsv([blank({ name: "a,b", version: 'say "hi"', product: "l1\nl2" })]);
    expect(out).toContain('"a,b"');
    expect(out).toContain('"say ""hi"""');
    expect(out).toContain('"l1\nl2"');
  });
  it("markdown", () => {
    expect(toMarkdown([ROW]).split("\n")).toEqual([
      "| Ecosystem | Name | Version | Found in | Product | End of support | Status |",
      "|---|---|---|---|---|---|---|",
      "| npm | react | ^18.2.0 | web/package.json | React |  | no EOL date |",
      "",
    ]);
  });
  it("markdown escapes pipes", () => {
    expect(toMarkdown([blank({ version: ">=1 || <2" })])).toContain(">=1 \\|\\| <2");
  });
  it("writes by extension, case-insensitively", async () => {
    const dir = await mkdtemp(join(tmpdir(), "sbom-"));
    try {
      await writeSbom(join(dir, "out.csv"), [ROW]);
      await writeSbom(join(dir, "out.MD"), [ROW]);
      expect(await readFile(join(dir, "out.csv"), "utf8")).toBe(toCsv([ROW]));
      expect(await readFile(join(dir, "out.MD"), "utf8")).toBe(toMarkdown([ROW]));
    } finally {
      await rm(dir, { recursive: true, force: true });
    }
  });
  it("rejects a bad extension", async () => {
    await expect(writeSbom("out.txt", [ROW])).rejects.toThrow(/\.csv or \.md/);
  });
});
