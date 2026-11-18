# eolchecker in TypeScript, with dependencies from the ecosystems' own SBOM plugins — design

Date: 2026-11-18
Builds on: `2026-11-11-eolchecker-design.md` and `2026-11-17-catalogue-docker-sbom-design.md`. Everything those documents say about the catalogue, matching, rows, statuses and the SBOM table stays true unless this document says otherwise.

## Intent

The owner wants eolchecker to be **as lightweight and maintainable as possible**, because it is about to be used in three places:

1. the command line on a developer's machine (as today),
2. a step in a Jenkins pipeline,
3. an Electron desktop app.

All three are used by **developers who already have the toolchains installed** (JDK + Maven, Node/npm, .NET SDK, PHP + Composer).

Today about half the code (~500 of ~1,800 lines) reimplements what the build tools already know: Maven property resolution and parent-pom chains, npm/yarn/pnpm lock-file parsing, Composer lock reading, NuGet `PackageReference`/central versions/`VersionOverride`. Most recent bug fixes landed in exactly that code. The owner's idea: stop parsing manifest text and ask the ecosystems' own tools instead.

## Decisions made with the owner

- **Dependency data comes from the ecosystems' own CycloneDX SBOM plugins** (Maven, npm, .NET, Composer), not from parsing manifests and not from a general scanner. Syft and Trivy were rejected as too big (28 MB / 50 MB downloads) for what they replace.
- **eolchecker runs the plugins itself** (approach A below), so the CLI, Jenkins and Electron behave the same.
- **Rewrite in TypeScript**, one codebase serving the CLI, the Jenkins step and the Electron app.
- **Users are developers with the toolchains installed.** No fallback to text parsing when a toolchain is missing.

## Goals

- `npx eolchecker <folder>` gives the same kind of report as today (terminal table, "Not recognised", `--sbom FILE.csv|.md`).
- The same package can be imported as a library by an Electron app (no printing, structured results, progress events).
- A machine-readable `--json` output for Jenkins and scripts.
- Remove all hand-written dependency parsing for Maven, npm, NuGet and Composer.
- Where a runtime version depends on build logic (Java via parent poms, .NET via `Directory.Build.props`), ask the build tool rather than reimplementing its rules.
- Missing toolchains or failing plugins are reported clearly, never silently skipped.

## Non-goals

- Building the Electron app's UI. This work only makes the library usable from Electron; the app is a separate project. *(My call.)*
- A Jenkinsfile or shared library. The step is "run `npx eolchecker`"; writing the pipeline is the owner's. *(My call.)*
- Transitive dependencies in the report. Still direct (declared) dependencies only.
- Gradle, CI configs, Kubernetes, Helm (unchanged from earlier designs).
- Installing toolchains or project dependencies. eolchecker never runs `npm install`, `composer install` or similar.
- Vulnerability scanning.

## Anti-goals

- **Silent gaps** (unchanged): a missing toolchain, a failing plugin or a missing lock file must appear under "Not recognised" with the reason and what to do, e.g. `backend/pom.xml: not scanned (Maven not found)`.
- **Ending up with more code to maintain than today.** No "plugin, else old parser" double paths.
- **Wrong END OF LIFE reports** (unchanged from the 2026-11-17 design): the matching rules and version-picking rules carry over exactly.

## Approaches considered

- **A. eolchecker runs the plugins itself (chosen).** Detects each ecosystem, runs its plugin, reads the CycloneDX JSON. One command everywhere. Needs the toolchains locally, which the users have.
- **B. Jenkins generates the SBOMs, eolchecker only reads them.** Local runs would still need today's parsers: two ways of reading dependencies to maintain. Rejected.
- **C. Plugin when the toolchain is present, today's parsers otherwise.** Most forgiving, but keeps all current code and adds more. Rejected.

Earlier rejected source options: `mvn dependency:list` / `npm ls` directly (each needs its own output parser; the CycloneDX plugins wrap these and give one common format), Syft/Trivy/cdxgen (large binaries or runtimes for what we need).

## Design

### 1. Shape of the package

- One npm package, `eolchecker`, written in TypeScript, targeting the current Node LTS. *(My call.)*
- **Library entry point**, roughly: `scan(root, { cacheDir?, onProgress?, signal? }) → Promise<Report>`. It never prints and never calls `process.exit`. `Report` holds table rows, SBOM rows and "Not recognised" entries (today's `Row`, `SbomRow`, `Unrecognised`).
- **CLI** (`bin: eolchecker`): `eolchecker <folder> [--sbom FILE] [--json]`. Prints the table as today; `--json` prints the `Report` as JSON to stdout instead of the table. Exit codes as today: 0 on success (whatever the statuses), 1 when the catalogue can't be loaded or `--sbom` can't be written, 2 for bad arguments/path. EOL findings don't change the exit code; a pipeline that wants to fail on EOL reads the JSON. *(My call, keeping the first design's "information, not judgements".)*
- `--no-maven` goes away: Maven is now the only way to read a pom. *(My call.)*
- **Electron**: the app imports the library and calls `scan` from its main process. Two things the library must allow: a `cacheDir` option (Electron passes its app-data folder; the CLI defaults to today's cache locations), and an `env`/`PATH` option, because apps launched from the macOS Dock don't inherit the shell's `PATH` and wouldn't find `mvn`, `npm`, `dotnet` or `composer`. Loading the login shell's environment is the Electron app's job. *(My call.)*
- Progress events (`onProgress`) replace today's "Asking Maven about …" stderr lines; the CLI prints them to stderr.

### 2. Running the plugins

Each ecosystem has a small "source" module: find the projects in the folder, run the tool, return direct dependencies per manifest file. All subprocesses go through one injectable runner (as `maven_fallback.Runner` today) so tests never run real tools. Each run has a timeout (today: 180 s) and is cancellable.

| Ecosystem | Trigger file | Command (pin exact versions in code) | Needs |
|---|---|---|---|
| Maven | top-most `pom.xml` of each reactor | `<mvnw or mvn> -B -q org.cyclonedx:cyclonedx-maven-plugin:<ver>:makeBom` (per module output in `target/`), written to a temp dir | JDK + Maven; network or a filled local repo |
| npm | `package.json` with a `package-lock.json` (or `node_modules`) | `@cyclonedx/cyclonedx-npm` with `--package-lock-only` when there's no `node_modules`, else without it. It is a normal dependency of the eolchecker package and run from there, not fetched with `npx` at scan time. | Node + npm |
| .NET | each `.sln`, else each project file without a solution | `dotnet-CycloneDX <sln/proj> --json -o <tmp>` (the `CycloneDX` .NET global tool) | .NET SDK + `dotnet tool install -g CycloneDX` |
| Composer | `composer.json` with a `composer.lock` | `composer CycloneDX:make-sbom --output-format=JSON --output-file=<tmp>` (global plugin `cyclonedx/cyclonedx-php-composer`) | PHP 8.1+, Composer, plugin installed globally |

- `./mvnw` is preferred over `mvn` exactly as `find_maven` does today.
- **Missing tool** → one "Not recognised" line per manifest: `not scanned (<tool> not found)`, plus a one-time hint how to install it for the two that need a one-time install (.NET tool, Composer plugin).
- **Missing lock file** (npm, Composer) → `not scanned (no lock file)`. The plugins can't resolve versions without one, and we never install.
- **Plugin fails** → `not scanned (<tool> failed: <first line of stderr>)`.
- **Same scopes as today** *(my call)*: npm `dependencies`, `devDependencies`, `peerDependencies`; Composer `require` and `require-dev`; every Maven scope including `test` and `provided`; all NuGet package references. Set each plugin's flags to include these (e.g. the Maven plugin's test-scope option), since some plugins leave them out by default.
- **Side effects** *(my call)*: scans behave like a developer's normal build. They may fill `~/.m2` and the NuGet cache, and may write into git-ignored build folders (`target/`, `obj/`, including a NuGet restore, which the .NET tool needs). Plugin output files go to a temp folder wherever the plugin allows it. eolchecker never changes tracked files, and never runs `npm install` or `composer install`. The README says this plainly.
- **Network** *(my call)*: the npm plugin ships inside eolchecker. The Maven plugin is fetched by Maven on first use, like any other plugin, so a Jenkins agent behind a proxy needs the same Maven settings as its builds. Offline with an empty cache → `not scanned (Maven failed: …)`.
- **When one run can't be split per project** *(my call)*: if a Maven multi-module or .NET solution BOM doesn't say which direct dependencies belong to which module/project, run the plugin once per module/project instead (slower, still correct). Never fall back to reporting transitive dependencies, or to the reactor root or `.sln` as "Found in".
- Exact command-line flags and how multi-module Maven output maps to modules are for the builder to verify against each plugin's current docs; the table above is the intent.

### 3. From a CycloneDX file to declared dependencies

- **Direct only**: take the components the project component (`metadata.component`, or each module's component in a multi-module BOM) lists in its `dependencies[].dependsOn`. Everything deeper is transitive and dropped.
- Every direct component becomes a `Dependency` with ecosystem, name, version and source file, exactly the type matching uses today. CycloneDX components carry a **purl**, which can feed straight into the existing purl matching (section 3 of the 2026-11-17 design).
- **Found in** = the manifest that declares it (the module's `pom.xml`, the `package.json`, the `.csproj`, the `composer.json`), as today. For .NET solutions this means mapping each project in the solution BOM back to its project file.
- Versions are always the resolved ones. The SBOM's Version column therefore shows `3.2.1`, not `^3.2.0`, for packages. *(Behaviour change, accepted with the plugin choice.)*

### 4. Runtime versions

| Runtime | Source | How |
|---|---|---|
| Java | Maven | Ask Maven for the **effective pom** of the reactor once (`help:effective-pom`, as today's fallback, but now always) and read `maven.compiler.release` / `.source` / `java.version` and the compiler plugin's `release`/`source` from it, with today's `1.8 → 8` rule. This replaces the in-repo parent-chain and property-resolution code. |
| .NET / .NET Framework | .NET SDK | `dotnet msbuild <proj> -getProperty:TargetFramework -getProperty:TargetFrameworks -getProperty:TargetFrameworkVersion`, which applies `Directory.Build.props`, conditions and properties itself. Then today's `parse_tfm` rules (one row per target, `netstandard*` ignored). If evaluation fails (e.g. old-style projects on macOS), read `<TargetFramework(s)>`/`<TargetFrameworkVersion>` directly from the project file only, without the props chain. *(My call; the builder should check old-style projects early.)* |
| .NET SDK | `global.json` | read directly, as today. |
| Node.js | `package.json` `engines.node`, `.nvmrc`, `.node-version` | read directly, as today (ranges keep their "as written" display). |
| PHP | `composer.json` `config.platform.php`, else `require.php` | read directly, as today. |

### 5. Docker

Port `docker.py` as it is: Dockerfiles and compose files, `FROM` lines, ARG/compose defaults, image product rows and OS rows. There is no plugin for this and the code is stable.

### 6. Ported unchanged

Catalogue download/cache/stale-copy fallback, purl and rule matching, row building and version picking, statuses, sorting, the SBOM CSV/Markdown writers and the terminal table. Behaviour as in the 2026-11-17 design. The terminal table needs a TypeScript table library or a small hand-written renderer (builder's choice).

### 7. Behaviour changes from today

- Maven `<parent>` and `<dependencyManagement>` entries no longer appear as their own dependencies; only real dependencies do. Spring Boot is still found via its starters (Maven group rule).
- The `(via Maven)` marker and `set by parent pom` gaps disappear: versions are always resolved or the module is "not scanned".
- Package versions show resolved versions, never ranges.
- Projects without a lock file (npm, Composer) or without the toolchain are "not scanned" instead of guessed from declared ranges.
- **yarn and pnpm projects are not scanned** (decided with the owner; they use neither). A `package.json` whose nearest lock file is `yarn.lock` or `pnpm-lock.yaml` gets `not scanned (yarn/pnpm not supported)`. Its `engines.node` runtime row is still read. The yarn/pnpm lock-file code in `npm.py` is not ported.

### 8. Moving over

- The TypeScript code lives in the same repo; the Python code stays until the TypeScript version reaches parity, then is removed in one commit. *(My call.)*
- **Parity check** before removing Python: run both on `examples/` and the test fixture repos, compare table and SBOM rows, and explain every difference by the behaviour changes in section 7.
- README rewritten for `npx`/Jenkins/library use and the toolchain requirements.

## Testing

- vitest *(my call)*, no network and no real tools in unit tests: the subprocess runner is faked and returns **recorded CycloneDX files** captured once from real plugin runs on small fixture projects (Maven single and multi-module, npm, npm workspace, .NET solution with central package management, Composer).
- Port the matching, rows, versions, catalogue, SBOM and Docker tests from pytest (about half of today's 180 tests). Detector tests for removed parsing are replaced by "recorded SBOM → declared dependencies" tests.
- Opt-in integration test (`EOLCHECKER_TOOLS=1`) that really runs the plugins on the fixture projects, for machines and Jenkins agents that have the toolchains.
- Keep the opt-in network guard test (`EOLCHECKER_NETWORK=1`) from the 2026-11-17 design.

## Left to the builder

- Module layout, types, and how `Report` is serialised for `--json` (stable field names, documented in the README).
- Exact plugin versions and flags, verified against current docs; how to map Maven multi-module and .NET solution BOMs back to manifest files.
- Whether plugins run in parallel across ecosystems.
- Table rendering library, HTTP client (Node's built-in `fetch` is enough), cache-dir helper.
- Build setup (tsc or a bundler), publishing details.
