# eolchecker — design

Date: 2026-11-11

## Intent

A small command-line tool that answers one question about a project: **are the major frameworks this repo runs on still supported?**

The owner works on solutions that mix Java/.NET back ends, Angular/React front ends, and PHP. Falling behind on a big framework (Spring Boot, Angular, .NET, PHP…) is expensive and easy to miss; falling behind on a small library usually isn't. So the tool deliberately looks only at the big frameworks and runtimes, and gives the plain facts: what version you're on, when its support ends, and what the newest release is.

It is used occasionally, by one person, against one repo at a time that is already cloned locally.

## Goals

- Point it at a local folder: `eolchecker ~/code/some-repo`.
- Find every supported framework/runtime anywhere in that folder (repos often hold several apps, e.g. `frontend/` + `backend/`).
- For each one found, print: component, version in use, file it was found in, end-of-support date, newest release overall, status.
- Say clearly when it found a build file but couldn't work out a version, instead of silently skipping.
- Adding another framework later should be a small, self-contained change.

## Non-goals

- Checking every dependency. Only the frameworks listed below.
- Security/vulnerability scanning.
- Reading Dockerfiles or CI configs for runtime versions. Build files only (decided with the owner).
- Gradle projects. The owner's projects use Maven only (decided with the owner).
- Cloning repos, taking URLs, or scanning many repos at once.
- Warnings or thresholds ("ending in 6 months"). The owner wants the info only, not judgements. Status is just *supported* or *end of life*.
- CI integration, JSON output, config files. (Not ruled out forever; just not now.)

## Anti-goals

- Noise: a long list of small libraries would defeat the purpose.
- Silent gaps: if the tool can't read something, the owner must be told. A clean-looking report that missed the back end is worse than no report.
- Maintaining our own list of EOL dates. Dates come from endoflife.date.

## Decisions made with the owner

- **Language:** Python. (Chosen over Java/Go/Node: least code for read-files/call-API/print-table; it's a personal, occasional tool.)
- **Input:** a path to a local folder already cloned. No git operations.
- **Data source:** the public endoflife.date API, live on each run (needs internet).
- **Output:** a table in the terminal, one row per component found.
- **No "ending soon" status**: just supported / end of life.
- **Latest column = newest release overall** (e.g. Spring Boot 4.0.x), not the newest patch in the current line.
- **Framework list:** start with ~15 of the most common, focused on Java/.NET, Angular/React, and PHP.

## Frameworks to check (initial 15)

All slugs verified to exist on endoflife.date on 2026-11-11.

| # | Component | endoflife.date slug | Where the version comes from |
|---|-----------|--------------------|------------------------------|
| 1 | Spring Boot | `spring-boot` | Maven: `spring-boot-starter-parent` parent version, or `spring-boot-dependencies` BOM import. |
| 2 | Spring Framework | `spring-framework` | Explicit `org.springframework:spring-*` dependency version or `spring-framework-bom`. |
| 3 | Java | `eclipse-temurin` | Maven: `maven.compiler.release` / `.source` / `java.version` property, or compiler plugin config. |
| 4 | Hibernate ORM | `hibernate-orm` | Explicit `org.hibernate(.orm):hibernate-core` version. |
| 5 | Apache Tomcat | `tomcat` | Explicit `org.apache.tomcat.embed:tomcat-embed-core` or `tomcat.version` property. |
| 6 | .NET (Core / 5+) | `dotnet` | `.csproj`/`.fsproj`/`.vbproj` `<TargetFramework(s)>` like `net8.0`, `netcoreapp3.1`; `global.json` `sdk.version`. |
| 7 | .NET Framework | `dotnetfx` | `<TargetFramework>` like `net48`, `net472`; old-style `<TargetFrameworkVersion>v4.8</TargetFrameworkVersion>`. |
| 8 | Angular | `angular` | `package.json` `@angular/core`. |
| 9 | AngularJS | `angularjs` | `package.json` `angular`. |
| 10 | React | `react` | `package.json` `react`. |
| 11 | Next.js | `nextjs` | `package.json` `next`. |
| 12 | Node.js | `nodejs` | `.nvmrc`, `.node-version`, `package.json` `engines.node`. |
| 13 | PHP | `php` | `composer.json` `require.php` or `config.platform.php`. |
| 14 | Laravel | `laravel` | `composer.json` / `composer.lock` `laravel/framework`. |
| 15 | Symfony | `symfony` | `composer.json` / `composer.lock` `symfony/framework-bundle` (fallback `symfony/http-kernel`). |

Easy next additions if wanted: Vue, jQuery, Drupal, WordPress, Quarkus, Kotlin, Maven, Nuxt, NestJS.

## Expected output

```
$ eolchecker ~/code/customer-portal

customer-portal

  Component     Version   Found in                End of support   Latest    Status
  ───────────── ───────── ─────────────────────── ──────────────── ───────── ───────────
  Spring Boot   3.1.5     backend/pom.xml         2024-06-30       4.0.1     END OF LIFE
  Java          17        backend/pom.xml         2029-09-30       25.0.1    supported
  Angular       16.2.0    frontend/package.json   2024-11-08       21.0.0    END OF LIFE
  Node.js       18        frontend/.nvmrc         2025-04-30       25.2.0    END OF LIFE
  .NET          8.0       api/Api.csproj          2026-11-10       10.0.0    END OF LIFE

  Not recognised: tools/pom.xml (couldn't read the Spring Boot version)
```

(Versions/dates above are illustrative.)

## Behaviour

**Scanning.** Walk the whole folder recursively. Skip `.git`, `node_modules`, `vendor`, `target`, `build`, `dist`, `bin`, `obj`, `.idea`, `.venv`.

**One row per (component, file).** If the same component appears in several files with the *same* version, still list each file. Matching a repo that has two Angular apps on different versions is exactly the case the owner wants to see.

**Version resolution.**
- Use the lock file when one sits next to the manifest (`package-lock.json`, `yarn.lock`, `pnpm-lock.yaml`, `composer.lock`), since it shows what's actually installed; otherwise use the declared version.
- For a declared range (`^16.2.0`, `~3.1`, `>=18`), use the lowest version it allows.
- Resolve simple Maven `${property}` references from the same `pom.xml`, and the parent pom if it's inside the repo. Don't fetch remote parents.
- **Maven fallback.** If reading a `pom.xml` directly leaves a gap (a version inherited from a parent outside the repo, or an unresolved property), and Maven is available (`./mvnw` in the repo, else `mvn` on the PATH), run `help:effective-pom` on that module and read the versions from its output. Mark those rows as resolved via Maven. If Maven isn't available or the command fails (no network, private repo needing credentials), fall back to "Not recognised" with the reason. A `--no-maven` flag skips this step. It's slower, and it downloads parent poms.

**API.** Use the endoflife.date **v1 API** (spec: https://endoflife.date/docs/api/v1/openapi.yml), base URL `https://endoflife.date/api/v1`. One `GET /products/{slug}` per product found. It returns `result.releases[]`, each with `name` (the cycle, e.g. `3.1`), `releaseDate`, `isEol`, `eolFrom`, and `latest.name`. Follow 301 redirects (products get renamed). Treat 404 as "product unknown" and 429/5xx as "couldn't fetch".

**Matching to endoflife.date.** endoflife.date groups releases into "cycles" (Spring Boot `3.1`, Angular `16`, Node `18`, .NET `8.0`, PHP `8.2`, .NET Framework `4.8` / `4.7.2`). Match the version to a cycle by trying the full version, then `major.minor`, then `major`. (Checked 2026-11-11: .NET 5+ cycles are named by major only, e.g. `8`, while older ones are `3.1`, `2.2`; .NET Framework uses `4.8`, `4.7.2`; Spring Boot and PHP use `major.minor`; Angular, React, Node, Temurin and Laravel use `major`.)

**Columns.**
- *End of support* = the release's `eolFrom`. If it's null, show "—".
- *Latest* = `latest.name` of the newest release for that product (the one with the most recent `releaseDate`).
- *Status* = *END OF LIFE* if `isEol` is true, otherwise *supported*. If no release matches, status is *unknown*.

**No published date.** Some products have no end-of-life date at all: React publishes none (endoflife.date shows every React major as not EOL with no date), and .NET Framework 4.6.2+ follows the Windows lifecycle. For these, show status *no EOL date* instead of *supported*, so an old React 17 doesn't look as healthy as React 19. The Latest column still shows how far behind you are.

**Ranges.** When the version comes from a range rather than a lock file (`"php": ">=7.4"`, `engines.node: ">=18"`), show the text as written in the Version column (e.g. `>=7.4`). The status is still based on the lowest version allowed, but you can see it's a minimum, not what actually runs.

**.NET specifics.** .NET projects often set the target in a shared `Directory.Build.props` file (in the project's folder or any parent folder up to the repo root) rather than in each `.csproj`. If a `.csproj` has no target of its own, look there, nearest first. A project with several targets (`<TargetFrameworks>net8.0;net48</TargetFrameworks>`) produces one row per target, which can mean a .NET row and a .NET Framework row from the same file. `netstandard*` targets are ignored, because they're API contracts with no support lifecycle.

**Not recognised.** Listed at the bottom, with a short reason: files where one of the 15 components is clearly in use but no version could be determined. Examples: `next` set to `"latest"`, a `pom.xml` with no Java version even after the Maven fallback, a Spring dependency managed only by a remote BOM. Build files that use none of the 15 components are skipped silently, to avoid noise. (Decided with the owner.)

**Errors.** Path doesn't exist → a clear message, exit code 2. endoflife.date unreachable → a clear message saying the dates couldn't be fetched, exit code 1. Nothing found → say "No supported frameworks found in <path>", exit code 0.

## Constraints

- Python 3.11+. The owner's machine currently has Python 3.7 as `python3`, so installation should use `uv`, which fetches a suitable Python automatically.
- Runs on macOS (owner's machine); should not do anything platform-specific.
- Needs internet access for endoflife.date. One request per product found per run is fine; no caching needed.
- Leave the existing IntelliJ project files (`.idea/`, `eolchecker.iml`) in place.

## Left to the builder

- Project layout, packaging (suggestion: `pyproject.toml` with a `eolchecker` console script, installable with `uv tool install .` or `pipx install .`).
- Libraries (suggestion: `httpx` or `requests` for HTTP, `rich` for the table).
- How each framework detector is structured, as long as adding one is a small, self-contained change.
- Tests: pytest with small fixture repos and a stubbed endoflife.date response.
- Exact table styling/colours.

## Calls I made (not discussed with the owner)

- Java dates come from the `eclipse-temurin` product (a common OpenJDK build) as a stand-in for "Java".
- Spring Framework, Hibernate and Tomcat are only reported when a pom in the repo declares them. When they only come in transitively (e.g. Tomcat via a starter), the Spring Boot row covers it. When they're declared without a version (Spring Boot or a parent picks it), the version is filled in from Maven's effective pom; without Maven they're listed under "Not recognised".
- Lock files win over declared versions; ranges use their lowest version.
- One row per file rather than merging duplicates.
- The example Latest column shows full versions, e.g. `4.0.1`.
- .NET multi-target projects give one row per target; `netstandard` is ignored.
- Status comes from the API's `isEol` flag rather than our own date comparison.
- The Maven fallback runs automatically, only when needed, with `--no-maven` to turn it off.
