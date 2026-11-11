# eolchecker: check every endoflife.date product — design

Date: 2026-11-11

## Intent

eolchecker today only knows ~15 hard-coded frameworks (see
`2026-11-11-eolchecker-design.md`). endoflife.date publishes, for each of its
489 products, the package identifiers (purls) that belong to it — e.g. the
`spring-boot` product lists `pkg:maven/org.springframework.boot/spring-boot-starter-web`
and ~20 more. Using those, eolchecker can check **every direct dependency the repo
declares against every product endoflife.date tracks**, without us maintaining
mappings by hand.

The owner runs the tool from this repo checkout (`uv run eolchecker <path>`) on a
laptop with internet, one repo at a time, and reads the full table.

This reverses two points of the original design, on purpose: "only the big
frameworks" (now: anything endoflife.date tracks — which is still a curated list,
so the "no noise" anti-goal holds) and "no config files" (now: one optional file
for the cache location).

## Goals

- Every direct dependency in npm, Composer, Maven and NuGet build files is turned
  into a purl and looked up in an index built from endoflife.date's purls.
- Everything that works today keeps working with the same results (no regressions).
- One request to endoflife.date per run, cached on disk.
- Save results as CSV.
- Optionally list dependencies endoflife.date doesn't track.
- README explains how to install and run the tool.

## Non-goals

- **Transitive dependencies.** Direct only (decided with the owner). Lock files
  are read only to get the exact version of a direct dependency, never to find new
  packages. No flag for transitive either.
- Ecosystems other than npm, Maven, Composer, NuGet (docker, rpm, deb, github purls
  are ignored). Gradle is still out.
- A bundled/offline copy of the product data. Laptops only, with internet (owner).
- Filtering (`--only-eol`) or a summary line. The full table is enough (owner).
- CPE or repology identifiers.

## Anti-goals

- A regression in what's reported today for the 15 existing components.
- Silent gaps: a tracked dependency whose version can't be read must appear under
  "Not recognised" (as today).
- One bad file or one network failure aborting the run.
- Many identical rows (e.g. one per Spring Boot starter).

## Decisions made with the owner

1. **Product data** comes from one `GET https://endoflife.date/api/v1/products/full`
   per run (verified 2026-11-11: 489 products, ~3 MB, each with `name`, `label`,
   `identifiers`, and `releases` identical to the per-product endpoint, including
   `name`, `releaseDate`, `isEol`, `eolFrom`, `latest.name`).
2. **Cache location:** inside the eolchecker checkout, in a git-ignored `.cache/`
   folder, by default. An optional config file can change it.
3. **Direct dependencies only.**
4. **All dependency kinds count:** npm `dependencies`, `devDependencies`,
   `peerDependencies`; Composer `require` and `require-dev`; Maven all scopes;
   every NuGet `PackageReference`.
5. **Keep the hard-coded lists** as overrides that win over the purl index.
6. **One row per product per build file**, checked against the **lowest** version
   found; other versions are shown as `3.2.0 (also 3.4.1)`. The row **names the
   dependencies** that matched.
7. **Full table**, no filters or summary.
8. **`--csv FILE`** saves the results as a plain CSV.
9. **Dependencies endoflife.date doesn't know are hidden by default**, listed with
   an option.

## Design

### Product catalogue and cache

- `EolClient` gets a method that returns all products from `/products/full`. The
  old per-product `releases()` call is no longer needed by the CLI.
- Cache: the response body is stored as `products-full.json`, plus its `ETag` and
  fetch time (format is the builder's choice). Each run sends `If-None-Match`; a
  `304` reuses the cached copy.
- If the request fails (network error, non-200/304, unparsable JSON) and a cached
  copy exists: use it and print one line to stderr, e.g.
  `endoflife.date unreachable; using data from 2026-11-09`.
  No cached copy: exit 1 with today's "Couldn't fetch…" message.
- `--refresh` skips `If-None-Match` and always downloads.
- **Default cache dir:** `<checkout>/.cache/`, where `<checkout>` is the folder
  holding eolchecker's own `pyproject.toml`, found relative to the package source
  (`src/eolchecker/` → two levels up). Add `.cache/` to `.gitignore`.
- **Config file:** optional `eolchecker.toml` in the checkout root:
  ```toml
  cache_dir = ".cache"   # relative paths are relative to the checkout root
  ```
  Read with `tomllib`. Unknown keys are ignored; an unreadable file prints a
  warning and defaults apply.
- *Builder's call / my call:* if no checkout is found (installed with
  `uv tool install`) or the cache dir isn't writable, fall back to the platform user
  cache dir (`~/Library/Caches/eolchecker` on macOS, `$XDG_CACHE_HOME` or
  `~/.cache/eolchecker` elsewhere) and say so in one stderr line. A failed cache
  write never fails the run.

### Purl index

Built from every product's `identifiers` of `type == "purl"` whose type is
`maven`, `npm`, `composer` or `nuget`.

Normalisation (*my call*), applied to both index entries and dependencies:
- Drop version (`@…`), qualifiers (`?…`) and subpath (`#…`) from index purls.
- Percent-decode (`%40angular` → `@angular`).
- Compare case-insensitively (Maven, NuGet, Composer are case-insensitive in
  practice; npm names are lowercase).
- Key = `(type, namespace/name)`, e.g. `("npm", "@angular/core")`,
  `("maven", "org.springframework.boot/spring-boot-starter-web")`,
  `("composer", "laravel/framework")`, `("nuget", "newtonsoft.json")`.

If one purl appears under several products, the builder should check the live
data (see "Left to the builder") and pick a deterministic rule; the index must not
silently drop a product.

The component name shown is the product's `label` (e.g. "Spring Boot"), except for
override components, which keep today's names from `models.COMPONENTS`.

### Dependency extraction (detectors)

Detectors still don't talk to the API and don't print. They now report every
direct dependency, not just allow-listed ones, as a purl key plus version
information (raw declared text, normalised version or none, source file, whether
the version came via Maven). Runtimes (Java, Node.js, PHP, .NET target frameworks
and SDK) and the existing special cases stay exactly as they are and are reported
as today's fixed components.

- **npm** (`package.json`): every name in `dependencies`, `devDependencies`,
  `peerDependencies`. Version from the nearest lock file (existing `_Lock` logic)
  else the lowest version the range allows (existing `lowest`). Non-registry
  specs (`file:`, `git+…`, `workspace:`, URLs) have no version.
- **Composer** (`composer.json`): every name in `require` and `require-dev`,
  except `php` and platform packages (`ext-*`, `lib-*`, `composer-*`). Version from
  `composer.lock` else lowest of range.
- **Maven** (`pom.xml`): every `<dependencies>/<dependency>` (all scopes) and every
  `<build>/<plugins>/<plugin>` (*my call*, since plugins are build-only deps the
  owner asked to include). `<dependencyManagement>` and `<pluginManagement>` entries
  are **only** a source of versions for the above, not dependencies themselves —
  except the existing overrides (e.g. Spring Boot from an imported
  `spring-boot-dependencies` BOM, Spring Boot from `spring-boot-starter-parent`),
  which keep working as today. Properties resolve as today (`${…}`, in-repo parent
  chain).
- **Maven versions not in the file** (*my call*): a tracked dependency without a
  version is **covered** (no gap) when the same product already has a version
  either (a) from another dependency or override in the same pom — e.g. starters
  under `spring-boot-starter-parent` join the Spring Boot row — or (b) from an
  in-repo parent pom: its resolved product versions or its
  `<dependencyManagement>` versions. Case (b) produces **no row** in the child (the
  parent's row covers it), matching today's
  `test_child_inherits_from_in_repo_parent`; this means `_parent_chain` must pass
  down the parent's resolved product versions and managed versions, not just
  properties and Boot/Java. Only uncovered ones are gaps, filled by the existing
  effective-pom fallback (once per pom); `--no-maven` still disables it. Goal: a
  multi-module repo must not start running Maven per module where it doesn't
  today.
- **NuGet** (new; `*.csproj`, `*.fsproj`, `*.vbproj`): every `<PackageReference>`
  with `Include` and a `Version` attribute or child element. Versions may come from
  central package management (`Directory.Packages.props`, `<PackageVersion>`),
  found from the project folder up to the scan root (*my call*). Also read
  `packages.config` (`<package id version>`) for older .NET Framework projects
  (*my call*). Version ranges like `[1.2,2.0)` use the lowest bound.
- **Untracked dependencies** (no product in the index): kept only for
  `--show-untracked`; an unreadable version on an untracked dependency is **not**
  a gap (it would be noise).
- **Tracked dependency, unreadable version:** goes to "Not recognised" as
  `couldn't read the <label> version`, like today — unless another dependency of
  the same product in the same file has a readable version, in which case it just
  joins that row by name (*my call*, same "covered" rule as Maven, all ecosystems).

Overrides: today's `PACKAGES` maps (npm, composer) and the Maven special cases
stay. Where an override and the purl index both match a dependency, the override's
component wins. Rows are keyed by (source file, product slug), so an override match
and index matches for the same product (e.g. `@angular/core` via override and
`@angular/common` via index) land in one row.

Because detectors need the index to know what's tracked (for the Maven gap rule),
the builder may either pass the index into detection via `Context`, or have
detectors report all dependencies and decide tracked/untracked/gap afterwards.
Either way: no network in detectors, and `main(argv, client, detectors)` stays
swappable with fakes.

### Rows and status

- **Package rows** (purl-index and package override matches): one row per
  (source file, product). **Runtime and special-case findings** (Java, Node.js,
  PHP, .NET target frameworks and SDK, and the Maven special cases) keep today's
  one-row-per-finding behaviour (*my call*, no regression): e.g.
  `<TargetFrameworks>net6.0;net8.0</TargetFrameworks>` still gives two .NET rows
  (`test_multi_target`). If a runtime finding and package matches hit the same
  product in the same file, the builder merges them into one row.
- For package rows, the version used for matching = lowest
  normalised version among the row's dependencies; if others differ, the Version
  column shows `<lowest display> (also <v2>, <v3>)`.
- Cycle matching as today (`cycle_candidates`: `4.7.2 → 4.7 → 4`).
- Statuses: `END OF LIFE`, `supported`, `no EOL date`, and **`unknown version`**
  (product known, no matching release cycle; replaces `unknown`).
  `not tracked` appears only for `--show-untracked` entries in the CSV.
- Columns: `Component`, `Dependencies`, `Version`, `Found in`, `End of support`,
  `Latest`, `Status`.
  - `Dependencies`: matched dependency names, comma-separated, e.g.
    `spring-boot-starter-web, spring-boot-starter-test`; for Maven use the
    artifactId only; for npm/composer/nuget the package name.
  - For runtimes and special cases: where the version came from, e.g.
    `maven.compiler.release`, `engines.node`, `.nvmrc`, `TargetFramework`,
    `global.json`, `spring-boot-starter-parent (parent)`, `require.php`.
  - `Found in` keeps the `(via Maven)` suffix.
- Order: by `Found in`, then today's `COMPONENTS` order for overrides, then other
  components alphabetically by label.
- If nothing is found: `No tracked dependencies found in <root>`.

### Output options

- `--show-untracked`: after the table, a section
  ```
  Not on endoflife.date:
    backend/pom.xml: lombok, junit-jupiter, …
  ```
  one line per file, names sorted.
- `--csv FILE`: writes a UTF-8, comma-separated CSV with a header row and the
  same columns as the table; dates `YYYY-MM-DD`; the Dependencies cell joined
  with `; `. "Not recognised" entries are appended as rows with status
  `not recognised` (reason in the Dependencies column — builder may add a `Note`
  column instead). With `--show-untracked`, untracked dependencies are appended as
  rows with status `not tracked`. The table still prints. If the file can't be
  written: error on stderr, exit 1, table still printed.
- Existing `--no-maven` unchanged.

### README

- **Install:** prerequisites (uv, Python ≥ 3.11 which uv can provide; optionally
  Maven or a project `mvnw` for the effective-pom fallback), clone, `uv sync`.
- **Run:** `uv run eolchecker ~/code/some-repo` from the checkout, with every
  option (`--no-maven`, `--csv`, `--show-untracked`, `--refresh`) and an example
  of the output. Mention `uv tool install .` as an alternative and that the cache
  then lives in the user cache folder.
- **Cache and config:** where the data is cached, how long (re-checked every run
  via ETag), `eolchecker.toml`.
- **What it checks:** rewritten — every direct dependency matched to endoflife.date
  by purl, plus the runtimes; direct only; which files are read (adds
  `packages.config`, `Directory.Packages.props`).
- **Development:** unchanged commands.

## Constraints

- Detectors separate from API and printing; `main()` keeps taking `client` and
  `detectors` so tests can swap in fakes.
- TDD with pytest (`uv run pytest`), no network in unit tests. The opt-in
  end-to-end test (`EOLCHECKER_NETWORK=1 uv run pytest tests/test_end_to_end.py`)
  is updated to the new flow.
- One bad file → "Not recognised" (as today). One network failure → cached copy
  or a clean exit 1, never a traceback.
- Python ≥ 3.11 (`tomllib` available); no new runtime dependencies unless needed
  (*my call*: none expected — the user-cache path can be computed by hand).

## Left to the builder

- **Check the live data first** (`/products/full`): purls listed under more than
  one product; purls with only a namespace or unusual shapes; whether every
  current override product's cycles still line up. Adjust normalisation if needed
  and record findings in the plan.
  Also check, for each product with npm/maven/composer/nuget purls, whether those
  packages' versions follow the product's release cycles (e.g. a client library
  or plugin versioned independently). Such purls are put in a small, documented
  **exclude list** next to the overrides (*my call*), with a test, so they can't
  pull a row's lowest version onto the wrong cycle. If none are found, the list
  starts empty but the mechanism exists.
- Cache file format and the exact `EolClient` API.
- Whether tracked/untracked is decided inside detectors (index in `Context`) or
  after detection.
- Exact stderr wording.
