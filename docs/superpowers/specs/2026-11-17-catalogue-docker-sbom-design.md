# eolchecker: every endoflife.date product, Docker, and an SBOM — design

Date: 2026-11-17
Builds on: `2026-11-11-eolchecker-design.md` (some of its non-goals are reversed here, see "What changes from the first design").
Related draft: `docs/superpowers/plans/2026-11-11-all-eol-products-prompt.md` (the owner's earlier notes on purl matching; this document supersedes it).

## Intent

Today eolchecker only checks ~15 hand-picked frameworks, matched through hand-written package-name lists, and ignores Dockerfiles. The owner wants three things:

1. **No hand-written package-name lists.** Any dependency that endoflife.date tracks should be checked, matched automatically from endoflife.date's own data. The owner asked "why do we have that at all?" and decided to drop the lists. The only hand-written logic kept is the *runtime rules* (how to read Java, Node.js, PHP and .NET versions out of build settings), because those are not packages and no catalogue can supply them.
2. **Docker.** Read Dockerfiles and compose files, report which version of each base image is used and whether it is end-of-life — including the operating system the image is built on (Debian, Ubuntu, Alpine), as its own row.
3. **An SBOM** — meaning, for the owner, *a list of every dependency the repo declares directly* (like the current scan, but complete), in CSV and Markdown so it can be pasted into a Confluence page as a table. Each row carries end-of-life status where endoflife.date tracks the dependency.

## Goals

- Match every directly declared dependency (npm, Maven, Composer, NuGet, Docker images) against the full endoflife.date catalogue, with no hand-written package or image names.
- Keep finding today's frameworks (Spring Boot, Spring Framework, Hibernate ORM, Angular, AngularJS, React, Next.js, Laravel, Symfony) through the catalogue plus general rules. One known exception, see "Known gaps".
- Keep the runtime rules for Java, Node.js, PHP, .NET and .NET Framework exactly as they work today.
- Dockerfiles and compose files: one row for the product in the image (e.g. Node.js 18), plus one row for the OS when the tag pins it (e.g. Debian 11 from `bullseye`).
- `--sbom FILE` writes all declared dependencies as CSV (`.csv`) or a Markdown table (`.md`).
- Distinguish "endoflife.date doesn't track this" from "tracked, but the version didn't match a release cycle".

## Non-goals

- Transitive dependencies. Direct (declared) dependencies only, as today. Lock files are used only to pin the version of a declared dependency.
- Standard SBOM formats (CycloneDX, SPDX). The owner wants a table to paste; CSV/Markdown is enough.
- Gradle, CI configs, Kubernetes manifests, Helm charts.
- Talking to Docker, registries, or running containers. Only files in the repo are read.
- Hand-written overrides or alias lists for packages or images.

## Anti-goals

- **Wrong "END OF LIFE" reports** from loose matching rules. A false alarm on a framework is worse than a missed small library. The fallback rules below are deliberately narrow, and each has tests with real-world counter-examples.
- **Silent loss of today's results.** A guard test checks that the frameworks found today are still found.
- **Noise in the terminal table.** The table only shows dependencies endoflife.date tracks (plus runtimes and Docker rows). Everything else appears only in the SBOM.

## Facts checked against the live catalogue (2026-11-17)

`GET https://endoflife.date/api/v1/products/full` returns 489 products (~3 MB) in one response. Each product has `name` (slug), `label`, `aliases`, `identifiers` (purl/cpe/repology) and `releases` (each with `name`, `codename`, `isEol`, `eolFrom`, `latest`, `releaseDate`, …).

- No purl (with version/qualifiers stripped) belongs to more than one product.
- purl counts in scope: `pkg:docker` 150, `pkg:oci` 45, `pkg:maven` 77, `pkg:npm` 31, `pkg:composer` 20, `pkg:nuget` 18.
- Good exact coverage: npm `@angular/core`, `angular`, `react`, `next`; Maven `spring-core`/`spring-context`/…, `hibernate-core`, `org.apache.tomcat:tomcat`; Docker `library/node`, `python`, `postgres`, `mysql`, `redis`, `golang`, `ruby`, `amazoncorretto`, `mariadb`, many `bitnami/*`, `cimg/*`.
- Gaps: Spring Boot lists only 22 artifacts (not `spring-boot-starter-parent`, not `-data-redis`, `-mail`, …). Symfony has no Composer purls. `php`, `nginx`, `tomcat`, `eclipse-temurin`, `debian`, `ubuntu`, `alpine` have no Docker purls (the products exist, under their name/aliases). `mcr.microsoft.com/dotnet/*` images are not listed at all. `dotnetfx` and `eclipse-temurin` have no package purls (they are runtimes here anyway).
- Maven groups in the catalogue map to exactly one product each, except `org.webjars` (jquery, jquery-ui).
- Debian and Ubuntu releases carry `codename` (e.g. Debian `12` → `Bookworm`; Ubuntu codenames are two words, e.g. `Jammy Jellyfish`). Alpine releases are numbered (`3.19`) and the product has alias `alpine`.

## Approaches considered

- **A. Exact purl matching only.** Simplest, purely endoflife.date's data. Rejected: Spring Boot (parent pom, most starters) and Symfony would mostly vanish, and common base images (php, nginx, eclipse-temurin, debian, alpine) would not be recognised.
- **B. Exact purl matching plus narrow, general fallback rules (chosen).** Still no hand-written names. More logic and some risk of wrong matches, contained by the rules' narrowness and tests.
- **C. A, plus contributing the missing identifiers upstream to endoflife.date.** Cleanest long term but depends on their review and timing. Worth doing alongside B (outside this work), not instead of it.

The owner picked **B**.

## Design

### 1. The catalogue

- Download `/api/v1/products/full` once, keep it in a local cache file, and reuse it for 24 hours. Location: the user cache folder (`~/Library/Caches/eolchecker/` on macOS, `$XDG_CACHE_HOME/eolchecker/` or `~/.cache/eolchecker/` elsewhere). *(My call.)*
- If the download fails and a cached copy exists (any age), use it and print a one-line warning to stderr saying how old it is. If there is no cached copy, exit 1 with the same kind of message as today ("Couldn't fetch end-of-life dates from endoflife.date: …"). *(My call.)*
- Release data comes from the same file, so the per-product `/products/<slug>` calls go away.
- The catalogue sits behind a small interface (e.g. `products()`, `releases(slug)`, `match(purl)`), and `main()` still takes it as a parameter (today's `client`) so tests use a fake catalogue built from a small JSON fixture. No network in unit tests.
- Status logic (`rows.build_rows`, cycle matching by shorter prefixes, `_tidy`, "latest = newest release overall") stays as is.

### 2. What every detector produces

Each detector returns, per file, **every directly declared dependency**: ecosystem, name, version (normalised, for matching), display version (as today: range text when no lock file), and source file. Runtime findings (Java, Node.js, PHP, .NET, .NET Framework) come from the unchanged runtime rules and carry their fixed product slug (`eclipse-temurin`, `nodejs`, `php`, `dotnet`, `dotnetfx`) — these slugs are part of the runtime rules, not a package list.

Detectors stay separate from the catalogue and from printing; matching happens afterwards in one place.

What counts as declared, per ecosystem:

- **npm** (`package.json`): `dependencies`, `devDependencies`, `peerDependencies` (today's sections). Version from the nearest lock file as today, else lowest version of the range. `engines.node`, `.nvmrc`, `.node-version` stay Node.js runtime rules.
- **Maven** (`pom.xml`): the `<parent>`, `<dependencies>`, and `<dependencyManagement>` entries (including BOM imports). Plugins are not included. *(My call: plugins are build tools, not what the app runs on.)* Property resolution and in-repo parent chain as today. Java stays a runtime rule.
  - **Missing versions.** Most Spring projects declare dependencies without versions (the parent or a BOM sets them). If any declared dependency's version can't be read directly and Maven is allowed, run the existing effective-pom fallback once for that pom and take versions from it — but only for the dependencies the file itself declares (the effective pom also contains inherited ones, which are not "declared here"). Rows filled this way keep the `(via Maven)` marker. This means Maven now runs for nearly every Spring project; the owner accepted that.
  - With `--no-maven`, or if Maven is missing/fails: a dependency whose product is tracked goes under "Not recognised" (as today, with the existing "(Maven not found)" / "(Maven fallback failed)" suffixes); in the SBOM its Version cell reads `set by parent pom`. *(My call.)*
- **Composer** (`composer.json`): `require` and `require-dev`, excluding `php` (runtime rule) and platform packages `ext-*`, `lib-*`, `composer-*`. Versions from `composer.lock` as today.
- **NuGet**: `<PackageReference Include=… Version=…>` in `.csproj/.fsproj/.vbproj` (attribute or child element), with versions from `Directory.Packages.props` `<PackageVersion>` when central package management is used, and `packages.config` for old .NET Framework projects. *(My call to include central versions and packages.config; both are common in the owner's .NET world.)* Target frameworks / `global.json` stay .NET runtime rules.
- **Docker**: see section 4.

### 3. Matching a dependency to a product

Build the dependency's purl and compare it with the catalogue's purls after normalising both (strip `@version`, `?qualifiers` except Docker/OCI `repository_url`, which is part of the name):

| Ecosystem | purl | Comparison |
|---|---|---|
| npm | `pkg:npm/<name>`, scope encoded as `%40` | percent-decode, lower-case |
| Maven | `pkg:maven/<group>/<artifact>` | case-sensitive |
| Composer | `pkg:composer/<vendor>/<name>` | lower-case |
| NuGet | `pkg:nuget/<id>` | case-insensitive |
| Docker | `pkg:docker/<namespace>/<name>`, Docker Hub official images as `library/<name>`; `pkg:oci/<name>?repository_url=<registry/path>` | lower-case; `docker.io/`, `index.docker.io/` and `registry-1.docker.io/` prefixes removed; `node` ≡ `library/node` |

Order of matching, first hit wins:

1. **Exact purl.**
2. **Maven group rule.** If every catalogue Maven purl with this dependency's exact `groupId` belongs to one single product, the dependency belongs to it (`org.springframework.boot:spring-boot-starter-parent` → Spring Boot). Exact group only — no prefix matching, because `org.springframework.data` must not become Spring Framework. Ambiguous groups (`org.webjars`) match nothing.
3. **Composer vendor rule.** Only for products that have **no** Composer purls at all: if the vendor equals the product's name or one of its aliases, the package belongs to it (`symfony/http-kernel` → Symfony). `laravel/sanctum` does **not** become Laravel, because Laravel has its own Composer purl.
4. **Docker name rule.** Only for Docker Hub official images (no namespace, or `library/`): if the image name equals a product's name or alias, it belongs to that product (`php`, `nginx`, `tomcat`, `eclipse-temurin`, `debian`, `ubuntu`, `alpine` → `alpine-linux`).

Matches from rules 2–4 are marked as rule matches internally (used when picking a row's version, below).

### 4. Docker files

Files read: `Dockerfile`, `Dockerfile.*`, `*.Dockerfile`, `*.dockerfile`, and compose files `docker-compose*.yml|yaml`, `compose*.yml|yaml`.

- **Dockerfile:** every `FROM` line. Ignore `--platform=…`. Skip `FROM scratch` and `FROM <name>` where `<name>` is an earlier stage's `AS` alias. Resolve `${VAR}`/`$VAR` from `ARG VAR=default` lines in the same file; a variable with no default goes under "Not recognised" ("image tag set by a build variable"). Strip `@sha256:…` digests; if only a digest is present, "Not recognised" ("image pinned by digest only").
- **Compose:** each `services.*.image`. `${VAR:-default}` / `${VAR-default}` use the default; otherwise "Not recognised".
- **Image name** → product via section 3. Images that match nothing still appear in the SBOM (ecosystem `Docker`, blank status) and not in the table.
- **Product version** from the tag: the leading version number (`18-alpine3.19` → `18`, `17-jre-jammy` → `17`, `3.12-slim-bookworm` → `3.12`). `latest`, no tag, or a tag with no leading number (e.g. `lts`, `bookworm` for a non-OS image) → "Not recognised" ("image tag doesn't pin a version"). For images that *are* an OS (`debian:bookworm-slim`, `ubuntu:jammy`), a codename tag resolves through the codename rule below.
- **OS row**, from the tag's other parts, split on `-`:
  - `alpine<number>` → Alpine Linux `<number>` (e.g. `alpine3.19` → 3.19). Plain `alpine` with no number → "Not recognised" ("Alpine version not pinned").
  - A part equal (case-insensitive) to a Debian or Ubuntu release's codename — for Ubuntu, the first word of the codename (`jammy`) — → that release. Codenames come from the catalogue, not a hand-written list.
  - Anything else (`slim`, `jre`, `fpm`, …) is ignored.
  - The OS row has the same source file; its Name in the SBOM is the OS product's label.
  - OS detection runs **independently of product matching** (decided with the owner): an image the tool doesn't recognise still gets its OS row, e.g. `registry.example.com/java-base:17-jammy` → Ubuntu 22.04. For images that are themselves the OS (`debian:bookworm`, `ubuntu:22.04`, `alpine:3.19`) only one row is produced.

### 5. Rows in the terminal table

- One row per matched product per source file, plus runtime rows and Docker OS rows. Untracked dependencies don't appear.
- Component column = the catalogue's `label` (e.g. "Spring Boot", "Debian").
- **When several dependencies in one file belong to the same product and disagree on version** *(my call, refining "lowest" from the conversation after seeing the data)*:
  - Only dependencies **with a readable version** take part. Versionless ones (e.g. Spring Boot starters with `--no-maven`) never decide the version.
  - If any of those matched by exact purl, use only those, and show the **lowest** version (most likely to be end-of-life, so nothing is hidden).
  - If all are rule matches, use the **most common** version, ties broken by the lowest. Reason: rule matches can catch packages with their own numbering (e.g. `symfony/polyfill-*` at 1.x next to Symfony 6.4 components); taking the lowest would falsely report "Symfony 1 END OF LIFE".
  - Example: a Spring Boot pom with `--no-maven` — the parent `spring-boot-starter-parent` 3.2.0 (rule match, has a version) sets the row; the versionless starters don't.
- **"Not recognised" for missing versions** *(my call)*: one line per product per file, not per dependency, and only when the product row got no version from any dependency in that file. So the Spring Boot example above prints a clean row and no "Not recognised" lines, as today.
- **Runtime findings bypass this merge** *(my call, to keep the runtime rules working exactly as today)*: `<TargetFrameworks>net6.0;net8.0</TargetFrameworks>` still gives two .NET rows. If a package (e.g. NuGet `Microsoft.NETCore.App`) matches the same product in the same file, it forms its own package row next to the runtime rows; neither replaces the other.
- Sorting: by "Found in", then Component alphabetically (replacing today's fixed `COMPONENTS` order).
- Status values: `END OF LIFE`, `supported`, `no EOL date`, and `version not found` (replaces `unknown`: product tracked, but no release cycle matched the version). "Not tracked" never appears in the table, only as a blank status in the SBOM.
- "Not recognised" section works as today.

### 6. The SBOM

- `eolchecker REPO --sbom FILE`. Format chosen by extension: `.csv` → CSV, `.md` → Markdown table; any other extension → exit 2 with a short message. The normal table is still printed. *(My call.)*
- One row per declared dependency per source file (deduplicated on ecosystem + name + source), including runtime rows (ecosystem `Runtime`, e.g. Name `Java`) and Docker image and OS rows.
- Columns: **Ecosystem** (`npm`, `Maven`, `Composer`, `NuGet`, `Docker`, `Runtime`), **Name** (`group:artifact` for Maven, image reference without tag for Docker), **Version** (display version), **Found in**, **Product** (catalogue label, blank if untracked), **End of support**, **Status**. *(Product column is my addition, so a reader sees why e.g. `spring-boot-starter-web` has a status.)*
- Each row's status is computed from **that dependency's own version**, except for rule matches *(my call, from the "no false END OF LIFE" anti-goal)*: a rule-matched dependency only gets End of support and Status when its version is in the same release cycle as the version its product row chose. Otherwise Product is filled and End of support/Status are blank. So `symfony/flex` 2.8 in a Symfony 6.4 project, or `org.hibernate:hibernate-validator` 6.2 next to `hibernate-core` 5.6, doesn't show a false "END OF LIFE". Untracked → Product, End of support and Status blank.
- Dedupe key is ecosystem + name + source, plus version for runtime rows (so `net6.0` and `net8.0` from one file stay two rows).
- Sorted by Found in, Ecosystem, Name.
- CSV: standard comma-separated with a header row, UTF-8. Markdown: a pipe table with header; `|` in values escaped. Both are meant to be pasted into Confluence (CSV via a spreadsheet or the CSV macro, Markdown directly).

### 7. Errors

- One bad file never stops the run (as today): unreadable/unparseable files go under "Not recognised".
- Catalogue failure: as in section 1.
- The `--sbom` file can't be written → message on stderr, exit 1, after printing the table.

## Known gaps (accepted)

- `org.apache.tomcat.embed:tomcat-embed-core` is not in the catalogue and the group rule is exact-group only, so Tomcat declared that way is no longer reported. (Today it is, when declared directly.) Candidate for an upstream contribution (approach C).
- `mcr.microsoft.com/dotnet/*` images are not recognised (not in the catalogue, and the name rule covers Docker Hub official images only). Their .NET version is usually also visible through the project files' target framework.
- Company-registry base images (e.g. `registry.example.com/java-base:17`) appear in the SBOM untracked; only their OS row (when the tag names one) carries a status.
- A rule match can still be wrong for a package with its own numbering in a shared group/vendor (e.g. an old `org.hibernate:hibernate-validator` alone in a pom would read as Hibernate ORM). The version-picking rule above limits the damage; tests cover the known cases.

## What changes from the first design

- "Checking every dependency" and "Reading Dockerfiles" were non-goals; they are now goals (the terminal table still only shows tracked products, keeping the "no noise" spirit).
- The hand-written lists (`COMPONENTS` package mapping, `PACKAGES` in the npm/composer detectors, the Spring/Hibernate/Tomcat logic in `maven.py`) go away. The rule "Spring Framework/Hibernate/Tomcat only when declared directly" disappears naturally, since only declared dependencies are read.

## Testing

- TDD with pytest, no network in unit tests: a small catalogue fixture (a handful of real products copied from the live response, including spring-boot, spring-framework, hibernate-orm, symfony, laravel, nodejs, php, debian, ubuntu, alpine-linux, eclipse-temurin, and an `org.webjars` pair).
- Rule tests with counter-examples: `org.springframework.data` not → Spring Framework; `laravel/sanctum` not → Laravel; `symfony/polyfill-*` doesn't drag Symfony's version down; `myorg/php` not matched by the Docker name rule; `org.webjars` ambiguous → no match.
- Docker parsing tests: multi-stage, `--platform`, ARG defaults, digests, `latest`, `-alpine` without number, codenames (`bullseye`, `bookworm-slim`, `jammy`), compose defaults.
- **Guard test** (opt-in network test, `EOLCHECKER_NETWORK=1`): a fixture repo with Spring Boot parent, a Spring Framework dependency, `hibernate-core`, Angular, AngularJS, React, Next.js, Laravel, Symfony, plus the runtimes, must yield all of them through the live catalogue.
- Existing tests for runtime rules keep passing; detector tests for removed hand-written logic are rewritten to the new output.

## Left to the builder

- Module layout (e.g. a `catalogue.py` with download/cache/index, a `matching.py`, a `detectors/docker.py`, an `sbom.py`), data types, and how the current `Finding`/`Row` types evolve.
- Exact cache file name and how the cache age check is implemented (no new dependency needed; `platformdirs` is acceptable if it keeps things simpler).
- README update: rewrite "What it checks" (any product endoflife.date tracks; runtime rules; Docker; `--sbom`), and note the known gaps.
