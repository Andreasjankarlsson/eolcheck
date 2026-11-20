# Parity check: Python vs TypeScript eolchecker

Date: 2026-11-20. This compares the Python version (`src/eolchecker/`) with the TypeScript
version (`src/*.ts`) before the Python code is removed (design
`docs/superpowers/specs/2026-11-18-typescript-cyclonedx-design.md`, section 8).

## How it was run

Both versions ran on separate temporary copies of each input, so Maven's `target/` and
.NET's `obj/` folders never landed in the repo or in `examples/`.

- Python: `eolchecker <copy> --sbom py.csv` (the project venv, same code as this branch).
- TypeScript: `npm run build`, then `node dist/cli.js <copy> --sbom ts.csv`, with
  `~/.dotnet/tools` added to `PATH`.
- Inputs: `examples/shop` (the owner's example repo) and every folder in
  `test/fixtures/projects/`. Two extra checks: a small Docker folder (Dockerfile with `ARG`,
  multi-stage `FROM`, `FROM $UNKNOWN`; compose file with a YAML merge key and a
  `${VAR:-default}` tag), and `examples/shop/api` without its `global.json` (see below).
- Machine: Maven 3 + JDK, Node/npm, .NET SDK 11.0.100 with the CycloneDX .NET tool 6.3.1.
  **Composer is not installed**, so every Composer project is "not scanned (Composer not
  found)" in TypeScript. **The .NET 6.0.428 SDK that `examples/shop/api/global.json` asks for
  is not installed either.**
- Both versions fetched the live endoflife.date catalogue.

The scanned copies were compared with the originals afterwards: apart from `target/` and
`obj/`, no file changed.

## Differences that are expected

Section numbers refer to the design document. "§7" is its list of accepted behaviour changes.

### Every input

| Difference | Explained by |
|---|---|
| The terminal table has no two-space indent and narrower column gaps. Same columns, same order, same rows apart from the ones listed below. | §6: the table renderer is the builder's choice. |
| Progress lines on stderr say `Running Maven in backend…`, `Running npm in .…`, `Running CycloneDX .NET tool on <project>…` instead of `Asking Maven about <pom>…`. | §1: progress events replace the "Asking Maven" lines. |

### examples/shop

| Difference | Python | TypeScript | Explained by |
|---|---|---|---|
| `backend/pom.xml` Spring Boot row | `Spring Boot 3.1.5 backend/pom.xml END OF LIFE` (from `spring-boot-starter-parent`) | no row; Spring Boot is still reported from the starter in `backend/orders/pom.xml` | §7: `<parent>` entries are no longer dependencies. |
| SBOM rows for parents | `com.example.shop:backend` (orders), `spring-boot-starter-parent` (backend), `com.example.corp:corp-parent` (reporting) | not listed | §7: `<parent>` entries are no longer dependencies. |
| `backend/orders/pom.xml` Spring Boot | `3.1.5`, Found in `backend/orders/pom.xml (via Maven)` | `3.1.5`, Found in `backend/orders/pom.xml` | §7: the `(via Maven)` marker goes away. |
| `backend/orders/pom.xml` Java | no row | `Java 17 supported` | §4: Java now comes from each module's effective pom, so a module that inherits `java.version` gets its own row; §7: no more "set by parent pom" gaps. |
| `legacy-admin/package.json` (no lock file) | `React ^16.14.0 no EOL date` row; SBOM rows `next latest`, `react ^16.14.0`, `react-dom ^16.14.0`; gap "couldn't read the Next.js version ('latest' isn't a version)" | gap `not scanned (no lock file)`, no npm rows | §7: projects without a lock file are "not scanned" instead of guessed from declared ranges. |
| `reporting/pom.xml` (its parent `com.example.corp:corp-parent:7` can't be downloaded) | gaps "couldn't read the Java version (Maven fallback failed)" and "couldn't read the Spring Boot version (set by parent pom, Maven fallback failed)"; SBOM row `spring-boot-starter-batch, set by parent pom` | gap `not scanned (Maven failed: exit code 1)`, no rows | §7: versions are always resolved or the module is "not scanned". Both versions say this pom couldn't be read. See concern 1 about the wording. |
| `web/composer.json` | `Guzzle 7.9.2`, `Laravel 10.48.22 END OF LIFE` | gap `not scanned (Composer not found)`; PHP row still there | §7: projects without the toolchain are "not scanned". Composer isn't installed on this machine. |
| `api/src/Api/Api.csproj` target framework | `.NET net6.0 END OF LIFE` (from `api/Directory.Build.props`) | gap `couldn't read the .NET target framework` | Missing toolchain: `api/global.json` pins SDK 6.0.428, which isn't installed, so `dotnet msbuild` can't evaluate the project. §4 then reads the project file alone, without the props chain, and `Api.csproj` has no target framework of its own. With `global.json` removed (extra check below) TypeScript reports `net6.0 END OF LIFE` exactly as Python. See concern 2. |
| `api/src/Api/Api.csproj`, `api/src/Shared/Shared.csproj` | (no package references, nothing reported) | gaps `not scanned (CycloneDX .NET tool failed: Unable to find local package cache locations...)` | Same missing SDK. §7 "without the toolchain"; the anti-goal "no silent gaps" asks for these lines. See concern 1 about the wording. |

Unchanged in `shop`: `.NET SDK 6.0.428`, `Shared.csproj` net8.0 / net48 (read from the project
file alone), `Billing.csproj` v4.6.1 (old-style project), Hibernate ORM status (but see U1),
both Node.js rows, Angular 16.2.12, `rxjs 7.8.1`, PHP `^8.1`.

### test/fixtures/projects/composer-app

| Difference | Python | TypeScript | Explained by |
|---|---|---|---|
| Composer packages | `Laravel 10.48.4 END OF LIFE`; SBOM `phpunit/phpunit 10.5.0` | gap `not scanned (Composer not found)`; PHP row still there | §7: projects without the toolchain are "not scanned". Composer isn't installed here. |

### test/fixtures/projects/dotnet-cpm

Same table rows and same SBOM (`Newtonsoft.Json 13.0.3`, `Serilog 3.1.0`, `net8.0`, SDK 8.0.100).
Only the formatting and progress differences above.

### test/fixtures/projects/maven-multi

| Difference | Python | TypeScript | Explained by |
|---|---|---|---|
| SBOM rows for the parent | `com.example:maven-multi 1.0.0` in `app/pom.xml` and `lib/pom.xml` | not listed | §7: `<parent>` entries are no longer dependencies. |

Table rows (Java 17, Spring Boot 3.3.5) and `junit:junit 4.13.2` are the same.

### test/fixtures/projects/npm-app

Same table and SBOM. Only formatting and progress.

### test/fixtures/projects/npm-workspace

| Difference | Python | TypeScript | Explained by |
|---|---|---|---|
| Extra SBOM row | — | `npm, a, 1.0.0, package.json` (the workspace root lists its member `a`) | Build ruling in Task 9: the root's own BOM lists its workspace members as dependencies; accepted as a harmless untracked SBOM row. It's not in endoflife.date, so it never gets a status. |
| Progress | — | `Running npm in .…` printed twice (root and member both run from the lock folder) | Task 9 ruling: a member is scanned from the lock folder with `-w <member>`. Cosmetic. |

### Docker (extra check)

Identical table, "Not recognised" lines and SBOM CSV (PostgreSQL 12, Redis 6.2-alpine,
nginx 1.18, Debian 11 from `node:18-bullseye`, Node.js, Python 3.8-slim; Alpine not pinned;
`FROM $UNKNOWN`).

### Not covered by these inputs

None of the inputs has a `packages.config`, a `yarn.lock`/`pnpm-lock.yaml`, or a project with
installed `node_modules` but no lock file, so the §7 changes "packages.config dependencies
now Found in the .csproj" and "yarn/pnpm not supported" didn't show up here. The unit and
tool tests cover them.

## No false END OF LIFE

No row is END OF LIFE in TypeScript that isn't END OF LIFE in Python. Every END OF LIFE row
TypeScript reports appears in Python's output with the same product, version, file and date.
The one new TypeScript row (`Java 17` in `backend/orders/pom.xml`) is `supported`.

The opposite does happen: TypeScript reports fewer END OF LIFE rows on `shop` (Spring Boot
from the parent, `net6.0` in `Api.csproj`, Laravel) and on `composer-app` (Laravel). Each one
is listed above with its reason, and each is replaced by a "Not recognised" line, except the
parent row, where Spring Boot is still found through the module's starter.

## Unexplained differences (bugs)

These don't fit any §7 change. They are left for the owner and the controller to decide on;
`src/` is unchanged in this step.

### U1. Package versions drop their qualifier (`6.2.13.Final` shows as `6.2.13`)

- Input: `examples/shop`, `backend/orders/pom.xml`, `hibernate-core` declared through
  `${hibernate.version}` = `6.2.13.Final`.
- Python: table `Hibernate ORM 6.2.13.Final`; SBOM `org.hibernate.orm:hibernate-core,6.2.13.Final`.
- TypeScript: table `Hibernate ORM 6.2.13`; SBOM `org.hibernate.orm:hibernate-core,6.2.13`.
  Maven's BOM (`target/eolchecker-bom.json`) has `"version": "6.2.13.Final"`.
- Diagnosis: `src/cyclonedx.ts`, `toDependency`: `return { ...base, version, display: version }`
  shows the normalised version. Python shows the version as written. The plan (Task 7) asked
  for this ("display = that normalised version"), but §7 only allows resolved versions
  instead of ranges, not shortened versions. The same happens to any package version with a
  suffix, e.g. npm `1.0.0-beta.2` would show as `1.0.0`, and the SBOM would then name a
  version that doesn't exist.
- Effect: display only. Matching and status use the normalised version in both versions, so
  this can't cause a false END OF LIFE.
- Possible fix: `display: text` (the raw resolved version), with a test in
  `test/cyclonedx.test.ts`.

### U2. SDK-implicit NuGet packages appear as dependencies

- Input: `examples/shop/api` with `global.json` removed (so the installed SDK can run),
  `src/Shared/Shared.csproj` (targets `net8.0;net48;netstandard2.0`, no `PackageReference`).
- Python: no NuGet rows for `Shared.csproj`.
- TypeScript: SBOM rows `NuGet, Microsoft.NETFramework.ReferenceAssemblies, 1.0.3` and
  `NuGet, NETStandard.Library, 2.0.3`, Found in `src/Shared/Shared.csproj`.
- Diagnosis: the CycloneDX .NET tool lists the packages the SDK adds by itself (for `net48` and
  `netstandard2.0` targets) as the project's direct dependencies. `src/sources/dotnet.ts`
  keeps everything the BOM lists. They aren't declared in the project, so the "declared
  dependencies only" rule says they shouldn't be there.
- Effect: SBOM only. Neither package is in endoflife.date, so no status and no false
  END OF LIFE. This would show on any machine where the project can be restored.
- Possible fix: drop these two well-known SDK-implicit package ids in `src/sources/dotnet.ts`,
  or accept them as a §7-style change.

## Concerns (expected behaviour, worth a look)

1. **Failure reasons can say little.** `describeFailure` (`src/tools.ts`) takes the first
   stderr line, as the spec says. Maven with `-q` writes its errors to stdout, so
   `reporting/pom.xml` shows `not scanned (Maven failed: exit code 1)` instead of "Non-resolvable
   parent POM". For `api/`, the .NET tool's first stderr line is
   `Unable to find local package cache locations...` while the real cause, further down, is
   "A compatible .NET SDK was not found. Requested SDK version: 6.0.428". Falling back to the
   first `[ERROR]`/`[FATAL]` stdout line for Maven, and looking for "compatible .NET SDK was
   not found" for dotnet, would make both clearer.
2. **The owner's example loses `net6.0 END OF LIFE` on this machine** because the SDK that
   `global.json` pins isn't installed and the §4 fallback reads the project file without
   `Directory.Build.props`. It is reported as a gap, not hidden, and a developer with that
   SDK gets the row. Python read the props file itself and didn't need the SDK.
3. Composer couldn't be checked against a real Composer run (not installed); its BOM shape
   comes from a hand-written fixture.
