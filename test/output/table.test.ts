import { describe, expect, it } from "vitest";
import { renderTable } from "../../src/output/table.js";
import type { Report, Row } from "../../src/rows.js";

const row = (over: Partial<Row> = {}): Row => ({
  component: "Java", version: "17", foundIn: "pom.xml", endOfSupport: "2029-09-30", latest: "17.0.9", status: "supported", ...over,
});
const report = (over: Partial<Report> = {}): Report => ({ rows: [row()], sbom: [], unrecognised: [], hints: [], ...over });
const ESC = String.fromCharCode(27);

describe("renderTable", () => {
  it("has the header in order, columns aligned", () => {
    const lines = renderTable("repo", report(), { color: false }).split("\n");
    const header = lines.find((l) => l.startsWith("Component"))!;
    expect(header).toContain("Component  Version  Found in  End of support  Latest  Status");
    const data = lines.find((l) => l.startsWith("Java"))!;
    expect(data.indexOf("17")).toBe(header.indexOf("Version"));
    expect(data.indexOf("supported")).toBe(header.indexOf("Status"));
  });
  it("pads columns to the widest cell plus two spaces", () => {
    const out = renderTable("r", report({ rows: [row(), row({ component: "PostgreSQL" })] }), { color: false });
    expect(out).toContain("Component   Version");
    expect(out).toContain("PostgreSQL  17");
  });
  it("says so with no rows", () => {
    expect(renderTable("r", report({ rows: [] }), { color: false })).toContain(
      "No dependencies tracked by endoflife.date found.",
    );
  });
  it("lists Not recognised sorted by source, then hints", () => {
    const out = renderTable(
      "r",
      report({
        unrecognised: [
          { source: "b/pom.xml", reason: "not scanned (Maven not found)" },
          { source: "a/package.json", reason: "not scanned (no lock file)" },
        ],
        hints: ["hint one", "hint two"],
      }),
      { color: false },
    );
    const lines = out.split("\n");
    const at = lines.indexOf("Not recognised:");
    expect(lines.slice(at + 1, at + 3)).toEqual([
      "  a/package.json: not scanned (no lock file)",
      "  b/pom.xml: not scanned (Maven not found)",
    ]);
    expect(out.indexOf("hint one")).toBeGreaterThan(out.indexOf("b/pom.xml"));
    expect(lines.indexOf("hint two")).toBe(lines.indexOf("hint one") + 1);
  });
  it("has no escapes without color", () => {
    expect(renderTable("r", report(), { color: false })).not.toContain(ESC);
  });
  it("styles statuses and the repo name with color", () => {
    const rows = [
      row({ status: "END OF LIFE" }),
      row({ status: "supported" }),
      row({ status: "no EOL date" }),
      row({ status: "version not found" }),
    ];
    const out = renderTable("repo", report({ rows }), { color: true });
    expect(out).toContain(`${ESC}[1m${ESC}[31mEND OF LIFE${ESC}[39m${ESC}[22m`);
    expect(out).toContain(`${ESC}[32msupported${ESC}[39m`);
    expect(out).toContain(`${ESC}[33mno EOL date${ESC}[39m`);
    expect(out).toContain(`${ESC}[2mversion not found${ESC}[22m`);
    expect(out).toContain(`${ESC}[1mrepo${ESC}[22m`);
  });
  it("leaves the repo name plain without color", () => {
    expect(renderTable("repo", report(), { color: false }).split("\n")[1]).toBe("repo");
  });
});
