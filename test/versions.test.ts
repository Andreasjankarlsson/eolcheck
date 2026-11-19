import { describe, expect, it } from "vitest";
import { cycleCandidates, isRange, lowest, normalise } from "../src/versions.js";

describe("versions", () => {
  it("normalise", () => {
    const cases: [string, string | null][] = [
      ["3.1.5", "3.1.5"], ["v6.4.1", "6.4.1"], ["6.4.1.Final", "6.4.1"],
      ["3.2.0-RC1", "3.2.0"], ["18", "18"], ["v18.17.0", "18.17.0"],
      ["latest", null], ["", null],
    ];
    for (const [raw, expected] of cases) expect(normalise(raw), raw).toBe(expected);
  });

  it("isRange", () => {
    const cases: [string, boolean][] = [
      ["^16.2.0", true], ["~3.1", true], [">=7.4", true], ["16.x", true],
      ["^7.4|^8.0", true], ["^7.4 || ^8.0", true], ["16.2.0", false], ["8.2", false],
    ];
    for (const [raw, expected] of cases) expect(isRange(raw), raw).toBe(expected);
  });

  it("lowest", () => {
    const cases: [string, string | null][] = [
      ["^16.2.0", "16.2.0"], ["~3.1", "3.1"], [">=7.4", "7.4"], ["16.x", "16"],
      ["^8.0|^7.4", "7.4"], ["^8.0 || ^7.4", "7.4"], [">=18 <21", "18"],
      ["16.2.0", "16.2.0"], ["*", null], ["latest", null],
      ["workspace:*", null], ["git+https://github.com/x/y.git", null],
      ["<20", null], ["<=18.0", null], ["<16 || >=18", "18"],
    ];
    for (const [raw, expected] of cases) expect(lowest(raw), raw).toBe(expected);
  });

  it("cycleCandidates", () => {
    expect(cycleCandidates("4.7.2")).toEqual(["4.7.2", "4.7", "4"]);
    expect(cycleCandidates("17")).toEqual(["17"]);
    expect(cycleCandidates("8.0")).toEqual(["8.0", "8"]);
  });
});
