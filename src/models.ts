/** Shared data types. */

export type Ecosystem = "npm" | "Maven" | "Composer" | "NuGet" | "Docker";

export type RuntimeName = "Java" | ".NET" | ".NET Framework" | "Node.js" | "PHP";

/** Runtime component name -> endoflife.date product slug. */
export const RUNTIMES: Record<RuntimeName, string> = {
  Java: "eclipse-temurin",
  ".NET": "dotnet",
  ".NET Framework": "dotnetfx",
  "Node.js": "nodejs",
  PHP: "php",
};

export interface Finding {
  component: RuntimeName;
  product: string;
  /** Normalised, used for matching. */
  version: string;
  /** What the Version column shows. */
  display: string;
  /** Declaring manifest, POSIX path relative to the scan root. */
  source: string;
}

export interface Dependency {
  ecosystem: Ecosystem;
  /** npm name; "group:artifact"; "vendor/pkg"; NuGet id; image ref without tag/digest. */
  name: string;
  /** Normalised for matching; null when unreadable. */
  version: string | null;
  /** What the Version column shows. */
  display: string;
  /** Declaring manifest, POSIX path relative to the scan root. */
  source: string;
  /** Short reason when version is null. */
  missing?: string;
  /** Docker only: full tag, for OS rows. */
  tag?: string;
}

export interface Unrecognised {
  source: string;
  reason: string;
}

export interface DetectResult {
  findings: Finding[];
  dependencies: Dependency[];
  unrecognised: Unrecognised[];
}

export function emptyResult(): DetectResult {
  return { findings: [], dependencies: [], unrecognised: [] };
}

export function merge(into: DetectResult, from: DetectResult): void {
  into.findings.push(...from.findings);
  into.dependencies.push(...from.dependencies);
  into.unrecognised.push(...from.unrecognised);
}

export function finding(
  component: RuntimeName,
  version: string,
  display: string,
  source: string,
): Finding {
  return { component, product: RUNTIMES[component], version, display, source };
}
