# eolchecker in TypeScript with CycloneDX plugins — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Python eolchecker with a TypeScript package (CLI + library) that gets declared dependencies from the ecosystems' own CycloneDX plugins, and gets runtime versions by asking the build tools.

**Architecture:** One npm package. `scan.ts` walks the folder and hands the file list to five *sources* (Maven, npm, .NET, Composer, Docker). The first four run a tool through one injectable `Runner` and turn its CycloneDX output into the same `Dependency`/`Finding`/`Unrecognised` types the Python code uses today. Catalogue, matching, rows, SBOM and table are straight ports of the Python modules, with the same behaviour.

**Tech Stack:** TypeScript (strict, ESM), Node ≥ 24, vitest, `yaml`, `fast-xml-parser`, `@cyclonedx/cyclonedx-npm` 7.0.1 (runtime dependency). Built-in `fetch`, `node:child_process`, `node:util` `styleText`.

**Spec:** `docs/superpowers/specs/2026-11-18-typescript-cyclonedx-design.md`, which builds on `2026-11-11-eolchecker-design.md` and `2026-11-17-catalogue-docker-sbom-design.md`. Read all three; the Python code in `src/eolchecker/` is the reference behaviour for every "port" task.

## Global Constraints

- Library code never prints and never calls `process.exit`. Only `src/cli.ts` does.
- Every subprocess goes through `Runner` (Task 6): argv array, no shell, timeout 180 000 ms, honours `AbortSignal`, uses the `env` passed in options (never `process.env` directly inside sources).
- Pinned plugin versions: `org.cyclonedx:cyclonedx-maven-plugin:2.9.1`, `@cyclonedx/cyclonedx-npm` `7.0.1` (exact, in `dependencies`), .NET tool `CycloneDX` `6.3.1`, Composer plugin `cyclonedx/cyclonedx-php-composer` `6.2.0`. Keep them as named constants in their source files.
- Never run `npm install`, `composer install` or anything that changes tracked files. Plugin outputs go to a temp dir from `fs.mkdtemp` (removed afterwards), except Maven, which writes `target/eolchecker-bom.json` per module (git-ignored build folder, allowed by the spec).
- Scopes as today: npm `dependencies`, `devDependencies`, `peerDependencies`; Composer `require` + `require-dev`; all Maven scopes, including `test`; all NuGet references.
- Direct dependencies only, never transitive. "Found in" is always the declaring manifest, as a POSIX path relative to the scan root.
- "Not recognised" wording (exact): `not scanned (<Tool> not found)`, `not scanned (no lock file)`, `not scanned (<Tool> failed: <first non-empty stderr line>)`, `not scanned (<Tool> timed out)`, `not scanned (yarn/pnpm not supported)`. Tool names: `Maven`, `npm`, `dotnet`, `CycloneDX .NET tool`, `Composer`, `Composer CycloneDX plugin`.
- Skip dirs: `.git`, `node_modules`, `vendor`, `target`, `build`, `dist`, `bin`, `obj`, `.idea`, `.venv` (from `scan.py`).
- Cache file: `products-full.json` in `cacheDir` (default as `default_cache_file()` in `catalogue.py`), max age 24 h, stale copy used with a warning on failure.
- Exit codes: 0 success, 1 catalogue unavailable or `--sbom` unwritable, 2 bad arguments/path/`--sbom` extension. EOL findings never change the exit code.
- The Python code (`src/eolchecker/`, `tests/`, `pyproject.toml`, `uv.lock`) is untouched until Task 16.
- Leave `.idea/` and `eolchecker.iml` in place.

## Review Focus

1. **npm workspace member** (`packages/a/package.json`, lock file only at the workspace root): expected to be scanned with Found in `packages/a/package.json`, not "no lock file". Test in Task 9.
2. **One Maven module fails** (unreachable private repo) in a multi-module build: the other modules are still reported; only the failing module is "not scanned (Maven failed: …)". Test in Task 8.
3. **A tool hangs:** the run continues, and that manifest shows `not scanned (<Tool> timed out)`. Tests in Task 6 and Task 8.
4. **Electron launched from the Dock** with a minimal PATH: tool lookup uses `options.env.PATH`, so passing the login shell's env finds the tools. Test in Task 6.
5. **Odd component versions in a BOM** (`github:user/repo`, `file:../lib`, no version): it becomes a Dependency with `version: null` and `missing: "'<raw>' isn't a version"` (or `"no version"`), and never throws. Test in Task 7.

---

## File structure

```
package.json  tsconfig.json  vitest.config.ts
src/index.ts            public API: scan(), types, ApiUnavailable
src/cli.ts              argument parsing, output, exit codes
src/models.ts           Finding, Dependency, Unrecognised, DetectResult, RUNTIMES, finding()
src/versions.ts         normalise, isRange, lowest, cycleCandidates
src/util.ts             dirsUp, readText, rel
src/catalogue.ts        Release, Product, Catalogue, parseCatalogue, loadCatalogue, ApiUnavailable
src/matching.ts         normalisePurl, dockerPurl, Matcher, osFromTag
src/rows.ts             Row, SbomRow, Report, buildReport
src/output/sbom.ts      toCsv, toMarkdown, writeSbom
src/output/table.ts     renderTable
src/tools.ts            Runner, runProcess, findTool, findMaven, describeFailure
src/cyclonedx.ts        directDependencies(bom, source)
src/scan.ts             SKIP_DIRS, listFiles, Source, ScanContext, detect
src/sources/{maven,npm,dotnet,composer,docker}.ts
test/**/*.test.ts       mirrors src/
test/fixtures/catalogue.ts      port of tests/catalogue_fixture.py
test/fixtures/boms/*.json       recorded CycloneDX outputs
test/fixtures/projects/*        small real projects used to record BOMs and for EOLCHECKER_TOOLS tests
```

Python keeps `tests/`; TypeScript uses `test/`. Add `node_modules/` and `dist/` to `.gitignore`.

---

### Task 1: Scaffold, models, versions, util

**Files:**
- Create: `package.json`, `tsconfig.json`, `vitest.config.ts`, `src/models.ts`, `src/versions.ts`, `src/util.ts`
- Modify: `.gitignore`
- Test: `test/versions.test.ts`, `test/util.test.ts`

**Interfaces:**
- Produces:
  - `type Ecosystem = "npm" | "Maven" | "Composer" | "NuGet" | "Docker"`
  - `type RuntimeName = "Java" | ".NET" | ".NET Framework" | "Node.js" | "PHP"`; `RUNTIMES: Record<RuntimeName, string>` (slugs from `models.py`)
  - `interface Finding { component: RuntimeName; product: string; version: string; display: string; source: string }`
  - `interface Dependency { ecosystem: Ecosystem; name: string; version: string | null; display: string; source: string; missing?: string; tag?: string }`
  - `interface Unrecognised { source: string; reason: string }`
  - `interface DetectResult { findings: Finding[]; dependencies: Dependency[]; unrecognised: Unrecognised[] }`; `emptyResult(): DetectResult`; `merge(into: DetectResult, from: DetectResult): void`
  - `finding(component: RuntimeName, version: string, display: string, source: string): Finding`
  - `normalise(raw: string): string | null`, `isRange(raw: string): boolean`, `lowest(raw: string): string | null`, `cycleCandidates(version: string): string[]`: same behaviour as `versions.py`
  - `dirsUp(start: string, root: string): string[]` (start → root inclusive), `readText(path: string): Promise<string>` (strips a UTF-8 BOM), `rel(root: string, path: string): string` (POSIX separators)

- [ ] **Step 1:** Create `package.json`: name `eolchecker`, `"type": "module"`, `"bin": {"eolchecker": "dist/cli.js"}`, `"main"`/`"types"` → `dist/index.js`/`dist/index.d.ts`, `"engines": {"node": ">=24"}`, scripts `build` (`tsc`), `test` (`vitest run`). Dependencies: `yaml`, `fast-xml-parser`, `@cyclonedx/cyclonedx-npm` at exactly `7.0.1`. Dev dependencies: `typescript`, `vitest`, `@types/node`. Run `npm install`.
- [ ] **Step 2:** `tsconfig.json`: strict, `module`/`moduleResolution` `NodeNext`, `target` ES2023, `rootDir` `src`, `outDir` `dist`, `declaration` true, include `src/**/*.ts`. `vitest.config.ts`: include `test/**/*.test.ts`.
- [ ] **Step 3: Write the failing tests.** Port every test in `tests/test_versions.py` to `test/versions.test.ts`, one `it` per pytest function, same inputs and expected values. In `test/util.test.ts`:
  - `dirsUp("/r/a/b", "/r")` equals `["/r/a/b", "/r/a", "/r"]`
  - `dirsUp("/x", "/r")` equals `["/x"]`
  - `readText` of a file starting with `﻿{}` returns `"{}"`
- [ ] **Step 4:** Run `npx vitest run test/versions.test.ts test/util.test.ts`. Expected: FAIL (modules missing).
- [ ] **Step 5:** Implement `src/models.ts`, `src/versions.ts` and `src/util.ts` with the signatures above.
- [ ] **Step 6:** Run the same command. Expected: PASS. Also run `npx tsc --noEmit`. Expected: no errors.
- [ ] **Step 7:** Commit: `git add package.json package-lock.json tsconfig.json vitest.config.ts .gitignore src test && git commit -m "feat(ts): scaffold package, models, versions"`

### Task 2: Catalogue

**Files:**
- Create: `src/catalogue.ts`, `test/fixtures/catalogue.ts`
- Test: `test/catalogue.test.ts`

**Interfaces:**
- Produces:
  - `interface Release { name: string; releaseDate: string; isEol: boolean; eolFrom: string | null; latest: string | null; codename: string | null }`
  - `interface Product { name: string; label: string; aliases: string[]; purls: string[]; releases: Release[] }`
  - `class Catalogue { constructor(products: Map<string, Product>); product(slug: string): Product | undefined; products(): Product[] }`
  - `class ApiUnavailable extends Error`
  - `parseCatalogue(data: unknown): Catalogue` (throws `ApiUnavailable("unexpected catalogue response")`)
  - `defaultCacheDir(env?: NodeJS.ProcessEnv): string`
  - `loadCatalogue(opts?: { cacheFile?: string; fetch?: typeof fetch; now?: number; warn?: (msg: string) => void }): Promise<Catalogue>`
  - `test/fixtures/catalogue.ts` exports `FULL` (the same products as `tests/catalogue_fixture.py`) and `catalogue(): Catalogue`.

- [ ] **Step 1: Write the failing tests.** Port every test in `tests/test_catalogue.py`. Replace the httpx stub with a fake `fetch`, `now` with the option, stderr with a `warn` spy. The stale-copy warning text stays exactly `Couldn't reach endoflife.date (<reason>); using a cached copy from <N day(s)|hour(s)> ago.`
- [ ] **Step 2:** Run `npx vitest run test/catalogue.test.ts`. Expected: FAIL.
- [ ] **Step 3:** Implement `src/catalogue.ts`. URL `https://endoflife.date/api/v1/products/full`, header `User-Agent: eolchecker/<package version>`, 30 s timeout via `AbortSignal.timeout`. Cache mtime is the age. A cache write failure is ignored.
- [ ] **Step 4:** Run the tests. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(ts): catalogue download and cache`

### Task 3: Matching

**Files:**
- Create: `src/matching.ts`
- Test: `test/matching.test.ts`

**Interfaces:**
- Consumes: `Catalogue`, `Dependency`.
- Produces: `normalisePurl(purl: string): string`, `dockerPurl(image: string): string`, `isOfficialImage(image: string): boolean`, `dependencyPurl(dep: Dependency): string`, `interface Match { product: string; byRule: boolean }`, `class Matcher { constructor(c: Catalogue); match(dep: Dependency): Match | null }`, `interface OsHit { product: string; version: string; display: string }`, `osFromTag(tag: string, c: Catalogue): { hits: OsHit[]; missing: [string, string][] }`.

- [ ] **Step 1: Write the failing tests.** Port every test in `tests/test_matching.py`, same inputs and expectations.
- [ ] **Step 2:** Run `npx vitest run test/matching.test.ts`. Expected: FAIL.
- [ ] **Step 3:** Port `matching.py` one-to-one: same rule order and the same `_unique` ambiguity handling. Use `decodeURIComponent` for `unquote`.
- [ ] **Step 4:** Run the tests. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(ts): purl and rule matching`

### Task 4: Rows and report

**Files:**
- Create: `src/rows.ts`
- Test: `test/rows.test.ts`

**Interfaces:**
- Consumes: `DetectResult`, `Catalogue`, `Matcher`, `osFromTag`, `cycleCandidates`.
- Produces:
  - `interface Row { component: string; version: string; foundIn: string; endOfSupport: string; latest: string; status: string }`
  - `interface SbomRow { ecosystem: string; name: string; version: string; foundIn: string; product: string; endOfSupport: string; status: string }`
  - `interface Report { rows: Row[]; sbom: SbomRow[]; unrecognised: Unrecognised[]; hints: string[] }`
  - `buildReport(result: DetectResult, catalogue: Catalogue, hints?: string[]): Report`
  - `DASH = "—"`

- [ ] **Step 1: Write the failing tests.** Port every test in `tests/test_rows.py`, dropping the `via_maven` assertions: the `(via Maven)` suffix and the `via_maven` field no longer exist. Add `it("passes hints through unchanged")`.
- [ ] **Step 2:** Run `npx vitest run test/rows.test.ts`. Expected: FAIL.
- [ ] **Step 3:** Port `rows.py`: `_choose`, the OS-row handling, the SBOM dedupe key (version included for `Runtime` and `Docker`), and the sorting. Dedupe `unrecognised` on `source + reason`, keeping first-seen order.
- [ ] **Step 4:** Run the tests. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(ts): table and SBOM rows`

### Task 5: Output (SBOM files, table)

**Files:**
- Create: `src/output/sbom.ts`, `src/output/table.ts`
- Test: `test/output/sbom.test.ts`, `test/output/table.test.ts`

**Interfaces:**
- Consumes: `Row`, `SbomRow`, `Unrecognised`.
- Produces: `toCsv(rows: SbomRow[]): string`, `toMarkdown(rows: SbomRow[]): string`, `writeSbom(path: string, rows: SbomRow[]): Promise<void>` (throws on an extension other than `.csv`/`.md`), `renderTable(repoName: string, report: Report, opts: { color: boolean }): string`.

- [ ] **Step 1: Write the failing tests.** Port every test in `tests/test_sbom.py`. CSV quoting follows Python's `csv` module: quote a field containing `,`, `"` or a newline, and double any `"`. Header: `Ecosystem,Name,Version,Found in,Product,End of support,Status`. In `table.test.ts`:
  - The header line contains `Component  Version  Found in  End of support  Latest  Status`, in that order, columns padded to the widest cell plus two spaces.
  - With no rows, the output contains `No dependencies tracked by endoflife.date found.`
  - "Not recognised:" lines are sorted by source and read `  <source>: <reason>`.
  - Hints print after "Not recognised", one per line.
  - With `color: false` there are no ANSI escapes. With `color: true`, `END OF LIFE` is bold red, `supported` green, `no EOL date` yellow and `version not found` dim (same as `STATUS_STYLE`).
- [ ] **Step 2:** Run `npx vitest run test/output`. Expected: FAIL.
- [ ] **Step 3:** Implement. Colour through `styleText` from `node:util`. The layout follows `report.py`: blank line, bold repo name, table, blank line, "Not recognised:", blank line.
- [ ] **Step 4:** Run the tests. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(ts): SBOM writers and terminal table`

### Task 6: Running tools

**Files:**
- Create: `src/tools.ts`
- Test: `test/tools.test.ts`

**Interfaces:**
- Produces:
  - `interface RunResult { code: number | null; stdout: string; stderr: string; timedOut: boolean }`
  - `type Runner = (cmd: string[], opts: { cwd: string; env: NodeJS.ProcessEnv; signal?: AbortSignal; timeoutMs?: number }) => Promise<RunResult>`
  - `runProcess: Runner`. It uses `spawn` with `shell: false` and a default timeout of 180 000 ms. A timeout kills the process and returns `timedOut: true`. An abort rejects with the `AbortError`. A spawn `ENOENT` returns `code: null` with stderr `"not found"`.
  - `findTool(name: string, env: NodeJS.ProcessEnv): Promise<string | null>`: the first executable `name` on `env.PATH`.
  - `findMaven(pomDir: string, root: string, env): Promise<string[] | null>`: the nearest executable `mvnw` from `pomDir` up to `root` (via `dirsUp`), else `findTool("mvn")`. Same rule as `find_maven`.
  - `describeFailure(tool: string, r: RunResult): string`: returns `not scanned (<tool> timed out)` or `not scanned (<tool> failed: <first non-empty stderr line, else "exit code N">)`.

- [ ] **Step 1: Write the failing tests:**
  - `it("finds a tool only on the PATH it is given")`: make a temp dir with an executable `fake-mvn`. `findTool("fake-mvn", {PATH: tmp})` returns its path, and `findTool("fake-mvn", {PATH: "/usr/bin"})` returns `null`. (Review Focus 4)
  - `it("prefers the nearest executable mvnw")`: `root/mvnw` and `root/a/mvnw` both executable; `findMaven(root/a/b, root, env)` returns `[root/a/mvnw]`. A non-executable `mvnw` is ignored.
  - `it("times out a hanging process")`: `runProcess([process.execPath, "-e", "setTimeout(()=>{}, 60000)"], {cwd, env: process.env, timeoutMs: 200})` resolves with `timedOut: true` in under 2 s. (Review Focus 3)
  - `it("passes arguments with spaces untouched")`: running `node -e "console.log(process.argv[1])" "a b"` gives stdout `a b\n`.
  - `it("describes failures")`: `describeFailure("Maven", {code: 1, stderr: "\n[ERROR] boom\nmore", stdout: "", timedOut: false})` equals `not scanned (Maven failed: [ERROR] boom)`. The timed-out case gives `not scanned (Maven timed out)`.
- [ ] **Step 2:** Run `npx vitest run test/tools.test.ts`. Expected: FAIL.
- [ ] **Step 3:** Implement `src/tools.ts`.
- [ ] **Step 4:** Run the tests. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(ts): subprocess runner and tool lookup`

### Task 7: CycloneDX reader

**Files:**
- Create: `src/cyclonedx.ts`, `test/fixtures/boms/minimal-npm.json`, `test/fixtures/boms/odd-versions.json`
- Test: `test/cyclonedx.test.ts`

**Interfaces:**
- Consumes: `Dependency`, `normalise`.
- Produces: `directDependencies(bom: unknown, source: string, rootRef?: string): Dependency[]`. Root = `rootRef` ?? `bom.metadata.component["bom-ref"]`. Direct = the refs in the `dependencies` entry whose `ref` is the root. Each ref is looked up in `components`, searched recursively, because cyclonedx-npm nests them.

Per component, read the purl:
- `pkg:npm/<ns?>/<name>` → ecosystem `npm`, name `@scope/name` (decoded) or `name`
- `pkg:maven/<g>/<a>` → `Maven`, `g:a`
- `pkg:nuget/<id>` → `NuGet`, `id` as written in the purl
- `pkg:composer/<v>/<n>` → `Composer`, `v/n`
- anything else, or no purl → skipped

Versions:
- `version` = `normalise(component.version)`
- `display` = that normalised version, or the raw text when it can't be normalised
- no version → `version: null, display: "", missing: "no version"`
- not a version → `version: null, missing: "'<raw>' isn't a version"`

Output is deduplicated on ecosystem + name, first one kept.

- [ ] **Step 1:** Write `minimal-npm.json` by hand: a CycloneDX 1.6 BOM with root `pkg:npm/app@1.0.0`, direct deps `@angular/core@16.2.0` and `react@18.2.0`, and a transitive `js-tokens` that only `react` depends on. Write `odd-versions.json` with direct deps whose versions are `github:user/repo`, `file:../lib`, and one without a version.
- [ ] **Step 2: Write the failing tests:**
  - `it("keeps only direct dependencies")`: names equal `["@angular/core", "react"]` and `js-tokens` is absent.
  - `it("maps purls to ecosystems and names")`: one table test per ecosystem line above.
  - `it("handles unreadable versions without throwing")` (Review Focus 5): the odd-versions BOM gives three Dependencies with `version: null` and the missing texts above.
  - `it("returns [] when the BOM has no dependencies section")`
- [ ] **Step 3:** Run `npx vitest run test/cyclonedx.test.ts`. Expected: FAIL.
- [ ] **Step 4:** Implement `src/cyclonedx.ts`.
- [ ] **Step 5:** Run the tests. Expected: PASS.
- [ ] **Step 6:** Commit: `feat(ts): read direct dependencies from CycloneDX`

### Task 8: Scan skeleton and Maven source

**Files:**
- Create: `src/scan.ts`, `src/sources/maven.ts`, `test/fixtures/projects/maven-multi/` (parent pom with modules `app` (jar, `maven.compiler.release` 17, depends on `spring-boot-starter-web` with test-scope `junit`) and `lib` (packaging `pom`)), and the recorded `test/fixtures/boms/maven-multi-app.json`, `maven-multi-lib.json`, `maven-multi-effective-pom.xml`
- Test: `test/scan.test.ts`, `test/sources/maven.test.ts`

**Interfaces:**
- Consumes: `Runner`, `findMaven`, `describeFailure`, `directDependencies`, `finding`.
- Produces:
  - `SKIP_DIRS: ReadonlySet<string>`; `listFiles(root: string): Promise<string[]>` (absolute paths, sorted, skipping SKIP_DIRS)
  - `interface ScanContext { root: string; env: NodeJS.ProcessEnv; run: Runner; signal?: AbortSignal; progress: (msg: string) => void; hint: (msg: string) => void }`
  - `interface Source { name: string; scan(files: string[], ctx: ScanContext): Promise<DetectResult> }`
  - `detect(root: string, ctx: ScanContext, sources: Source[]): Promise<DetectResult>`: lists the files once and runs every source. A source that throws gives `couldn't scan with <name>` for the root (`source: "."`). The output is merged, with `unrecognised` deduped.
  - `mavenSource: Source`; `javaVersion(raw: string): string | null` (port of `java_version`)

Maven behaviour:
1. Take all `pom.xml` files, shallowest first. For each pom not yet covered, find Maven (`findMaven`). If there's none, every remaining pom in that directory tree gets `not scanned (Maven not found)`. Otherwise run, with `cwd` = the pom's folder:
   `[...maven, "-B", "-q", "--fail-at-end", "-f", pom, "org.cyclonedx:cyclonedx-maven-plugin:2.9.1:makeBom", "-DoutputFormat=json", "-DoutputName=eolchecker-bom", "-DincludeTestScope=true", "help:effective-pom", "-Doutput=<tmp>/effective-pom.xml"]`
2. Afterwards, every pom whose folder has `target/eolchecker-bom.json` is covered. Read its dependencies with `directDependencies(bom, rel(pom))`.
3. The effective pom (a single `<project>` or a `<projects>` wrapper) is matched to each covered pom by `groupId:artifactId`, taken from the BOM's `metadata.component` (`group`, `name`). From the matched project, read Java the same way `read_pom` does: `maven.compiler.release` / `maven.compiler.source` / `java.version`, then the compiler plugin's `release`/`source`. That gives `finding("Java", javaVersion(raw), raw, rel(pom))`. A non-`pom` packaging with no Java value → `couldn't read the Java version`.
4. A pom the run did not cover → `describeFailure("Maven", result)`. After a failed run, poms that are still uncovered get one retry with `-f` on themselves (their own reactor); after that they are reported as failed.
5. Progress message: `Running Maven in <rel dir>…`. Delete the temp dir afterwards.

- [ ] **Step 1:** Create the `maven-multi` fixture project. Record its BOMs by running the command above on it (Maven is installed on the dev machine), then copy `app/target/eolchecker-bom.json`, `lib/target/eolchecker-bom.json` and the effective pom into `test/fixtures/boms/`. Delete `target/`.
- [ ] **Step 2: Write the failing tests** with a fake `Runner` that writes the recorded files to where the real command would put them:
  - `scan.test.ts`: `it("skips node_modules and target")`, `it("reports a throwing source without stopping others")`.
  - `it("reads direct Maven dependencies per module")`: `app/pom.xml` lists `org.springframework.boot:spring-boot-starter-web` and the test-scoped `junit` dependency, with Found in `app/pom.xml`.
  - `it("reads Java from the effective pom")`: a Java `17` finding for `app/pom.xml`, and no Java gap for `lib` (packaging pom).
  - `it("passes the pinned plugin and test scope")`: the recorded command contains `org.cyclonedx:cyclonedx-maven-plugin:2.9.1:makeBom` and `-DincludeTestScope=true`.
  - `it("reports Maven missing")`: with no mvnw and an empty PATH, every pom gets `not scanned (Maven not found)`.
  - `it("keeps the modules that built when one fails")` (Review Focus 2): the fake writes only app's BOM and exits 1 with stderr `[ERROR] Could not resolve dependencies`. app is reported, and lib gets `not scanned (Maven failed: [ERROR] Could not resolve dependencies)` after the retry also fails.
  - `it("reports a timeout")` (Review Focus 3): the fake returns `timedOut: true`, and the poms get `not scanned (Maven timed out)`.
- [ ] **Step 3:** Run `npx vitest run test/scan.test.ts test/sources/maven.test.ts`. Expected: FAIL.
- [ ] **Step 4:** Implement `src/scan.ts` and `src/sources/maven.ts`. Port the `java_version` tests from `tests/detectors/test_maven.py` into `maven.test.ts`.
- [ ] **Step 5:** Run the tests. Expected: PASS.
- [ ] **Step 6:** Commit: `feat(ts): scan skeleton and Maven source`

### Task 9: npm source

**Files:**
- Create: `src/sources/npm.ts`; fixture projects `test/fixtures/projects/npm-app/` (package.json with a dependency, a devDependency, a peerDependency and `engines.node: ">=18"`, plus package-lock.json) and `npm-workspace/` (root lock, member `packages/a`); recorded `test/fixtures/boms/npm-app.json` and `npm-workspace-a.json`
- Test: `test/sources/npm.test.ts`

**Interfaces:**
- Consumes: `ScanContext`, `Runner`, `findTool`, `directDependencies`, `lowest`, `isRange`, `normalise`, `dirsUp`.
- Produces: `npmSource: Source`.

npm behaviour:
- For each `package.json`, the nearest lock file found via `dirsUp` (`package-lock.json`, `yarn.lock` or `pnpm-lock.yaml`, checked in that order per folder) decides what happens:
  - `yarn.lock`/`pnpm-lock.yaml` → `not scanned (yarn/pnpm not supported)`.
  - No lock and no `node_modules` next to the package → `not scanned (no lock file)`.
  - Otherwise, check `findTool("npm")` (needed by the plugin; missing → `not scanned (npm not found)`). Then run in the package folder: `[process.execPath, <bin of @cyclonedx/cyclonedx-npm resolved via import.meta.resolve>, "--output-format", "JSON", "--output-file", "<tmp>/bom.json", ...(node_modules present ? [] : ["--package-lock-only"])]`. Pass `env` with `NODE_ENV` removed and `npm_config_omit` set to empty, so dev and peer dependencies stay included. Dependencies come from `directDependencies(bom, rel(package.json))`.
- `engines.node`, `.nvmrc` and `.node-version` → Node.js findings exactly as `npm.py` does (`lowest`, range display), whether or not the dependency scan worked.

- [ ] **Step 1:** Create both fixture projects (`npm install --package-lock-only --ignore-scripts` to make the locks). Record their BOMs by running the command above, and store them in `test/fixtures/boms/`.
- [ ] **Step 2: Write the failing tests** (fake Runner returning the recorded BOMs):
  - `it("includes dev and peer dependencies")`: all three declared names are present; the recorded command contains `--package-lock-only`, and the env passed has no `NODE_ENV`.
  - `it("scans a workspace member using the root lock")` (Review Focus 1): `packages/a/package.json` is scanned (cwd `packages/a`), Found in `packages/a/package.json`.
  - `it("reports yarn and pnpm as not scanned")`: one test each, and the Node.js engine row is still read.
  - `it("reports a missing lock file")`
  - Port the Node.js runtime tests (`.nvmrc`, `.node-version`, `engines`) from `tests/detectors/test_npm.py`.
- [ ] **Step 3:** Run `npx vitest run test/sources/npm.test.ts`. Expected: FAIL.
- [ ] **Step 4:** Implement `src/sources/npm.ts`.
- [ ] **Step 5:** Run the tests. Expected: PASS.
- [ ] **Step 6:** Commit: `feat(ts): npm source`

### Task 10: .NET source

**Files:**
- Create: `src/sources/dotnet.ts`; fixture `test/fixtures/projects/dotnet-cpm/` (`Directory.Build.props` with `<TargetFramework>net8.0</TargetFramework>`, `Directory.Packages.props` with central versions, `src/Api/Api.csproj` with two `PackageReference`s, one with `VersionOverride`, and `global.json`); `test/fixtures/boms/dotnet-api.json`
- Test: `test/sources/dotnet.test.ts`

**Interfaces:**
- Consumes: `ScanContext`, `findTool`, `describeFailure`, `directDependencies`, `finding`.
- Produces: `dotnetSource: Source`; `parseTfm(tfm: string): [".NET" | ".NET Framework", string] | null` (port of `parse_tfm`).

.NET behaviour, per project file (`.csproj`, `.fsproj`, `.vbproj`). Solutions are not used; running per project avoids mapping solution BOMs back to projects, which is the spec's allowed "run once per project":
- Packages:
  - `dotnet` missing → `not scanned (dotnet not found)`.
  - `dotnet-CycloneDX` missing → `not scanned (CycloneDX .NET tool not found)`, plus one hint per run: `Install the CycloneDX .NET tool: dotnet tool install --global CycloneDX --version 6.3.1`.
  - Otherwise run `["dotnet-CycloneDX", project, "--output-format", "Json", "--output", tmp, "--filename", "bom.json"]` with cwd = the project folder. Check these flags against `dotnet-CycloneDX --help` for 6.3.1 when recording, and fix them there if they differ. Dependencies come from `directDependencies(bom, rel(project))`.
- Target framework:
  - Run `["dotnet", "msbuild", project, "-getProperty:TargetFramework", "-getProperty:TargetFrameworks", "-getProperty:TargetFrameworkVersion"]`; stdout is JSON `{"Properties": {...}}`.
  - If dotnet is missing, the command fails, or the JSON can't be parsed, read those three properties straight from the project file's `<PropertyGroup>`s only (via `fast-xml-parser`, ignoring namespaces).
  - Then apply the existing rules: split on `;`, skip `netstandard*`, `parseTfm`, one finding per target, display = the TFM text. Nothing found → `couldn't read the .NET target framework`.
- `global.json` → `.NET` finding with display `SDK <version>`, as in `dotnet.py`.

- [ ] **Step 1:** Create the fixture. If the .NET SDK and CycloneDX tool are installed, record `dotnet-api.json`. If not, write it by hand as a CycloneDX 1.6 BOM with root = the Api project and its two packages as direct deps, and leave a comment in the test that it's hand-written and gets verified by Task 15's tool test.
- [ ] **Step 2: Write the failing tests:**
  - `it("reads package references from the tool's BOM")`: two NuGet deps, Found in `src/Api/Api.csproj`.
  - `it("asks msbuild for the target framework")`: a fake msbuild stdout `{"Properties":{"TargetFramework":"","TargetFrameworks":"net8.0;net48","TargetFrameworkVersion":""}}` gives one `.NET 8.0` and one `.NET Framework 4.8` finding.
  - `it("falls back to the project file when msbuild fails")`: msbuild exits 1, and the project's own `<TargetFramework>net6.0</TargetFramework>` is read.
  - `it("reports the CycloneDX tool missing with an install hint")`: the hint is given exactly once with two projects.
  - Port the `parse_tfm`, `netstandard` and `global.json` tests from `tests/detectors/test_dotnet.py`.
- [ ] **Step 3:** Run `npx vitest run test/sources/dotnet.test.ts`. Expected: FAIL.
- [ ] **Step 4:** Implement `src/sources/dotnet.ts`.
- [ ] **Step 5:** Run the tests. Expected: PASS.
- [ ] **Step 6:** Commit: `feat(ts): .NET source`

### Task 11: Composer source

**Files:**
- Create: `src/sources/composer.ts`; fixture `test/fixtures/projects/composer-app/` (composer.json requiring `php: ^8.1` and `laravel/framework`, with a `require-dev` package, plus composer.lock); `test/fixtures/boms/composer-app.json`
- Test: `test/sources/composer.test.ts`

**Interfaces:**
- Consumes: `ScanContext`, `findTool`, `describeFailure`, `directDependencies`, `lowest`, `isRange`, `finding`.
- Produces: `composerSource: Source`.

Composer behaviour:
- For each `composer.json`:
  - no `composer.lock` next to it → `not scanned (no lock file)`
  - no `composer` → `not scanned (Composer not found)`
  - otherwise run `["composer", "--no-interaction", "--working-dir", dir, "CycloneDX:make-sbom", "--output-format=JSON", "--output-file=<tmp>/bom.json", "composer.json"]`
- If stderr contains `is not defined` (the plugin isn't installed) → `not scanned (Composer CycloneDX plugin not found)`, plus one hint per run: `Install the Composer CycloneDX plugin: composer global config --no-plugins allow-plugins.cyclonedx/cyclonedx-php-composer true && composer global require cyclonedx/cyclonedx-php-composer:6.2.0`. Any other failure → `describeFailure("Composer", r)`.
- Dependencies come from `directDependencies`, keeping only names containing `/`.
- PHP: `config.platform.php`, else `require.php`, read from composer.json as `composer.py` does (`lowest`, range display).

- [ ] **Step 1:** Create the fixture. Record the BOM if Composer is available, otherwise write it by hand, following the rule in Task 10 Step 1.
- [ ] **Step 2: Write the failing tests:** `it("includes require-dev packages")`, `it("reports a missing plugin with a hint")`, `it("reports a missing lock file")`. Also port the PHP runtime tests from `tests/detectors/test_composer.py`.
- [ ] **Step 3:** Run `npx vitest run test/sources/composer.test.ts`. Expected: FAIL.
- [ ] **Step 4:** Implement `src/sources/composer.ts`.
- [ ] **Step 5:** Run the tests. Expected: PASS.
- [ ] **Step 6:** Commit: `feat(ts): Composer source`

### Task 12: Docker source

**Files:**
- Create: `src/sources/docker.ts`
- Test: `test/sources/docker.test.ts`

**Interfaces:**
- Consumes: `Dependency`, `normalise`, `readText`, `rel`, the `yaml` package.
- Produces: `dockerSource: Source`, `splitImage(ref: string): [string, string | null, string | null]`.

- [ ] **Step 1: Write the failing tests.** Port every test in `tests/detectors/test_docker.py`.
- [ ] **Step 2:** Run `npx vitest run test/sources/docker.test.ts`. Expected: FAIL.
- [ ] **Step 3:** Port `docker.py` one-to-one: file-name rules, logical lines, ARG defaults, stage aliases, compose `${VAR:-d}`, and the four reason strings.
- [ ] **Step 4:** Run the tests. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(ts): Docker source`

### Task 13: Library API

**Files:**
- Create: `src/index.ts`
- Test: `test/index.test.ts`

**Interfaces:**
- Consumes: `detect`, all five sources, `loadCatalogue`, `buildReport`.
- Produces:
  - `interface ScanOptions { cacheDir?: string; env?: NodeJS.ProcessEnv; onProgress?: (msg: string) => void; warn?: (msg: string) => void; signal?: AbortSignal; runner?: Runner; catalogue?: () => Promise<Catalogue> }`
  - `scan(root: string, options?: ScanOptions): Promise<Report>`
  - re-exports `Report`, `Row`, `SbomRow`, `Unrecognised`, `ApiUnavailable`, `writeSbom`, `renderTable`

How `scan` works:
- `env` defaults to `process.env`, `runner` to `runProcess`, and `catalogue` to `loadCatalogue({cacheFile: join(cacheDir ?? defaultCacheDir(env), "products-full.json"), warn})`.
- Hints are collected and deduplicated in order.
- When detection found nothing at all, return an empty report without loading the catalogue.
- `ApiUnavailable` propagates.

- [ ] **Step 1: Write the failing tests:**
  - `it("returns an empty report without touching the catalogue for an empty folder")`: the catalogue factory spy is not called.
  - `it("uses the cacheDir option")`: with a fake fetch and a temp cacheDir, `<cacheDir>/products-full.json` exists afterwards.
  - `it("never writes to stdout")`: spy on `process.stdout.write` during a scan of a Docker-only fixture; no calls.
  - `it("forwards progress messages")`
  - `it("passes options.env to the runner")`
- [ ] **Step 2:** Run `npx vitest run test/index.test.ts`. Expected: FAIL.
- [ ] **Step 3:** Implement `src/index.ts`.
- [ ] **Step 4:** Run the tests. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(ts): library entry point`

### Task 14: CLI

**Files:**
- Create: `src/cli.ts` (with a `#!/usr/bin/env node` line)
- Test: `test/cli.test.ts`

**Interfaces:**
- Consumes: `scan`, `renderTable`, `writeSbom`, `ApiUnavailable`.
- Produces: `main(argv: string[], deps?: { scan?: typeof scan; stdout?: (s: string) => void; stderr?: (s: string) => void; isTTY?: boolean }): Promise<number>`. The file ends by calling `process.exit(await main(process.argv.slice(2)))` when it is run as the entry module.

Usage: `eolchecker <path> [--sbom FILE] [--json]`, parsed with `node:util` `parseArgs`.

Messages, same wording as `cli.py`:
- `--sbom file must end in .csv or .md` → exit 2
- `Path not found: <p>` → exit 2
- `Not a folder: <p>` → exit 2
- `Couldn't fetch end-of-life dates from endoflife.date: <msg>` on stderr → exit 1
- `No dependencies found in <root>` → exit 0
- `SBOM written to <path>` after the table
- `Couldn't write <path>: <reason>` → exit 1

Output:
- `--json` prints `JSON.stringify(report, null, 2)` and no table; `--sbom` still works with it.
- Progress and warnings go to stderr.
- Colour only when stdout is a TTY.

- [ ] **Step 1: Write the failing tests.** Port every test in `tests/test_cli.py`, except the ones about `--no-maven` and `(via Maven)`. Add:
  - `it("prints the report as JSON with --json")`: `JSON.parse(stdout)` has the keys `rows`, `sbom`, `unrecognised`, `hints`.
  - `it("rejects --no-maven")`: exit 2.
  - `it("exits 0 when something is END OF LIFE")`
- [ ] **Step 2:** Run `npx vitest run test/cli.test.ts`. Expected: FAIL.
- [ ] **Step 3:** Implement `src/cli.ts`.
- [ ] **Step 4:** Run `npx vitest run` and `npm run build`. Expected: all PASS, and `dist/cli.js` exists. `node dist/cli.js --help` prints the usage.
- [ ] **Step 5:** Commit: `feat(ts): command line`

### Task 15: Real-tool and network tests

**Files:**
- Create: `test/tools.integration.test.ts`, `test/network.integration.test.ts`

**Interfaces:**
- Consumes: `scan`, the fixture projects from Tasks 8–11, and the guard-test fixture repo (port it from `tests/test_end_to_end.py`).

- [ ] **Step 1:** `tools.integration.test.ts`: `describe.skipIf(process.env.EOLCHECKER_TOOLS !== "1")`. For each fixture project whose tool `findTool` finds, run the real `scan` with the fixture catalogue and assert the same dependency names and runtime findings that the unit tests assert from the recorded BOMs. Skip a project, with a visible `it.skip` reason, when its tool is missing. This is where the hand-written .NET and Composer BOMs get checked against the real tools.
- [ ] **Step 2:** `network.integration.test.ts`: `describe.skipIf(process.env.EOLCHECKER_NETWORK !== "1")`. Port `tests/test_end_to_end.py` against the live catalogue. It also needs the tools, so skip any ecosystem whose tool is missing, as in Step 1.
- [ ] **Step 3:** Run `EOLCHECKER_TOOLS=1 npx vitest run test/tools.integration.test.ts`. Expected: the Maven and npm projects PASS on the dev machine; the others PASS or are skipped with a reason. Run plain `npx vitest run`. Expected: both files skipped, everything else PASS.
- [ ] **Step 4:** Commit: `test(ts): opt-in real-tool and network tests`

### Task 16: Parity check, README, remove Python

**Files:**
- Create: `docs/parity-notes.md`
- Modify: `README.md`, `.gitignore`
- Delete (only after Step 3): `src/eolchecker/`, `tests/`, `pyproject.toml`, `uv.lock`

- [ ] **Step 1:** Run both versions on the owner's example repo (git-ignored, so it lives in the main checkout: `/Users/andreaskarlsson/Documents/eolchecker/examples/shop`) and on each folder in `test/fixtures/projects/`:
  - `uv run eolchecker <dir> --sbom /tmp/py.csv`
  - `node dist/cli.js <dir> --sbom /tmp/ts.csv`

  Diff the tables and the CSVs. In `docs/parity-notes.md`, list every difference and the spec section-7 behaviour change that explains it. Expected kinds:
  - no `<parent>`/`<dependencyManagement>` rows
  - resolved versions instead of ranges
  - `packages.config` dependencies now Found in the `.csproj`
  - not scanned because of no lock file, yarn/pnpm, or a missing tool
  - no `(via Maven)`

  A difference that doesn't fit one of these is a bug: fix it in the owning task's source, with a test, before going on.
- [ ] **Step 2:** Rewrite `README.md`:
  - install (`npm install -g .` / `npx`)
  - use: CLI flags, `--json` field list, library `scan()` example for Electron, including passing `env` and `cacheDir`
  - Jenkins: run `npx eolchecker . --json` after the build; agents need the toolchains and normal Maven proxy settings
  - toolchain requirements and the two one-time installs (.NET tool, Composer plugin)
  - side effects (`target/`, `obj/`, `~/.m2`, NuGet cache; never touches tracked files)
  - yarn/pnpm not supported
  - known gaps carried over
  - development (`npm test`, `EOLCHECKER_TOOLS=1`, `EOLCHECKER_NETWORK=1`)
- [ ] **Step 3: Stop and show the owner `docs/parity-notes.md`.** Delete the Python code only after they confirm.
- [ ] **Step 4:** `git rm -r src/eolchecker tests pyproject.toml uv.lock`, and remove the Python-only lines from `.gitignore`. Run `npx vitest run && npm run build`. Expected: PASS.
- [ ] **Step 5:** Commit: `chore: replace Python implementation with TypeScript`
