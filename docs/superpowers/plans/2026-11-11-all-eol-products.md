# Check every endoflife.date product — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Check every direct dependency (npm, Composer, Maven, NuGet) against every endoflife.date product, matched by purl, using one cached `/products/full` request per run.

**Architecture:** A new `catalog` module parses `/products/full` into `Product`s and builds a `PurlIndex` (purl key → products, with today's hard-coded packages as overrides). A new `cache` module fetches it with ETag and keeps a copy on disk. Detectors report every direct dependency as a `Dependency` (purl key + version) next to today's runtime `Finding`s; they get the index through `Context` only to decide what counts as a gap. `rows.build_rows` groups dependencies into one row per (file, product) and merges them with runtime findings; `report` prints the table, the untracked section and the CSV.

**Tech Stack:** Python ≥ 3.11 (`tomllib`, `csv`), httpx, rich, pyyaml, pytest, uv.

**Spec:** `docs/superpowers/specs/2026-11-11-all-eol-products-design.md`

## Global Constraints

- Direct dependencies only; lock files only supply versions of direct dependencies.
- Detectors never touch the network and never print table output; `main(argv, client, detectors, cache_dir)` stays swappable with fakes.
- No network in unit tests. E2E only with `EOLCHECKER_NETWORK=1`.
- One bad file → "Not recognised"; one network failure → cached copy or exit 1 with `Couldn't fetch end-of-life dates from endoflife.date: <reason>`. Never a traceback.
- No new runtime dependencies.
- Statuses exactly: `END OF LIFE`, `supported`, `no EOL date`, `unknown version`, `not tracked`, `not recognised` (last two in CSV/untracked only, plus `not tracked` for an override product missing from the catalogue).
- Table columns exactly: `Component`, `Dependencies`, `Version`, `Found in`, `End of support`, `Latest`, `Status`.
- Options exactly: `--no-maven`, `--csv FILE`, `--show-untracked`, `--refresh`.
- Existing behaviour for the 15 components must not regress; when an existing test has to change, the plan says so and why.
- Run all tests with `uv run pytest`.

## Review Focus

1. **Multi-module Maven repo:** a child pom whose tracked dependency is versionless but covered by an in-repo parent must not run Maven. Product already reported by the parent → no row in the child; version only in the parent's `<dependencyManagement>` → child row with that version (spec said "no row" here, but then nothing would report it; this plan fixes that). Tests in Task 7.
2. **Corrupt or half-written cache files** (truncated JSON, missing meta) must be treated as "no cache", never crash. Test in Task 2.
3. **Name casing and encoding:** `Newtonsoft.Json` vs `newtonsoft.json`, `pkg:npm/%40angular/core@16.0.0?x=y#sub`. Tests in Task 1.
4. **The same package declared twice in one file** (e.g. `dependencies` and `devDependencies`, or `<dependency>` and `<plugin>`) appears once in the Dependencies cell and once in the untracked list. Test in Task 3.
5. **`--csv` to a folder that doesn't exist** → stderr error, exit 1, table still printed. Test in Task 9.

---

## File Structure

- Create `src/eolchecker/catalog.py` — `Product`, `Match`, `parse_products`, `purl_key`, `dep_key`, `PurlIndex`, `EXCLUDED_PURLS`.
- Create `src/eolchecker/cache.py` — checkout/config/cache-dir lookup and `load_catalog`.
- Create `src/eolchecker/detectors/nuget.py` — PackageReference, `packages.config`, `Directory.Packages.props`.
- Create `tests/fakes.py` — `product()`, `payload()`, `FakeClient` shared by tests.
- Modify `api.py` (replace `releases()` with `products_full()`), `models.py` (`Dependency`, `OVERRIDES`, `Finding.origin`), `detectors/__init__.py` (`Context.index`, register NuGet), `npm.py`, `composer.py`, `dotnet.py`, `maven.py`, `rows.py`, `report.py`, `cli.py`, `README.md`, `.gitignore`, and the matching tests.

---

### Task 1: Catalogue and purl index

**Files:**
- Create: `src/eolchecker/catalog.py`, `tests/fakes.py`, `tests/test_catalog.py`
- Modify: `src/eolchecker/models.py`, `src/eolchecker/detectors/__init__.py`, `src/eolchecker/api.py` (move release parsing out)

**Interfaces:**
- Produces:
  - `models.OVERRIDES: dict[str, str]` — dep key → component name:
    `{"npm:@angular/core": "Angular", "npm:angular": "AngularJS", "npm:react": "React", "npm:next": "Next.js", "composer:laravel/framework": "Laravel", "composer:symfony/framework-bundle": "Symfony", "composer:symfony/http-kernel": "Symfony"}`
  - `catalog.Product(slug: str, label: str, releases: tuple[Release, ...], purls: tuple[str, ...])` (frozen)
  - `catalog.Match(component: str, product: str)` (frozen)
  - `catalog.parse_products(body: bytes) -> list[Product]` — raises `ApiUnavailable("unexpected response for products/full")` on bad shape.
  - `catalog.parse_release(raw: dict) -> Release` (moved from `api.py`, same field mapping).
  - `catalog.purl_key(purl: str) -> str | None`
  - `catalog.dep_key(ecosystem: str, name: str) -> str` — `"<ecosystem>:<name>"`, lowercased.
  - `catalog.PurlIndex(products: Iterable[Product] = ())` with `.resolve(key: str) -> list[Match]` and `.releases(slug: str) -> list[Release] | None`
  - `catalog.EXCLUDED_PURLS: frozenset[str]` (dep keys)
  - `detectors.Context(root, use_maven=True, index: PurlIndex = PurlIndex())` — use `field(default_factory=PurlIndex)`.
  - `tests/fakes.py`: `product(slug, label, purls=(), releases=()) -> dict` (one product as the API returns it, `identifiers` of type purl), `payload(*products: dict) -> bytes` (`{"schema_version": "1.2.1", "total": n, "result": [...]}`), `index(*products: dict) -> PurlIndex`, `rel(name, release_date, is_eol, eol_from, latest) -> dict` (one release as the API returns it).

- [ ] **Step 1: Check the live data** (network allowed for this step only; don't commit the script). Fetch `https://endoflife.date/api/v1/products/full` into `$CLAUDE_JOB_DIR/tmp` (or any scratch dir) and, with a throwaway script, list: (a) npm/maven/composer/nuget purl keys claimed by more than one product; (b) purls of those types without a name part or with qualifiers/subpaths; (c) for each product with such purls, the purl list next to its release cycle names — flag packages whose versions plainly don't follow the product's cycles (separately versioned clients/plugins); (d) confirm all 15 `COMPONENTS` slugs exist. Write the findings as a comment block at the top of `EXCLUDED_PURLS` and put the flagged keys in it (empty set if none).

- [ ] **Step 2: Write the failing tests** in `tests/test_catalog.py`

```python
@pytest.mark.parametrize("purl,key", [
    ("pkg:npm/%40angular/core", "npm:@angular/core"),
    ("pkg:npm/%40angular/core@16.0.0?x=y#sub", "npm:@angular/core"),
    ("pkg:maven/org.springframework.boot/spring-boot-starter-web", "maven:org.springframework.boot/spring-boot-starter-web"),
    ("pkg:nuget/Newtonsoft.Json", "nuget:newtonsoft.json"),
    ("pkg:composer/laravel/framework", "composer:laravel/framework"),
    ("pkg:docker/library/nginx", None),
    ("pkg:github/foo/bar", None),
    ("not a purl", None),
])
def test_purl_key(purl, key): assert purl_key(purl) == key

def test_dep_key_lowercases(): assert dep_key("nuget", "Newtonsoft.Json") == "nuget:newtonsoft.json"

def test_parse_products_and_resolve():
    body = payload(product("spring-boot", "Spring Boot",
                           ["pkg:maven/org.springframework.boot/spring-boot-starter-web"],
                           [{"name": "3.4", "releaseDate": "2024-11-21", "isEol": False, "eolFrom": "2025-12-31",
                             "latest": {"name": "3.4.1"}}]))
    idx = PurlIndex(parse_products(body))
    assert idx.resolve("maven:org.springframework.boot/spring-boot-starter-web") == [Match("Spring Boot", "spring-boot")]
    assert idx.releases("spring-boot")[0].name == "3.4"
    assert idx.resolve("maven:org.projectlombok/lombok") == []
    assert idx.releases("nope") is None

def test_overrides_win_and_use_component_names():
    idx = PurlIndex(parse_products(payload(product("angular", "Angular (label)", ["pkg:npm/%40angular/core"]))))
    assert idx.resolve("npm:@angular/core") == [Match("Angular", "angular")]
    assert PurlIndex().resolve("npm:react") == [Match("React", "react")]  # overrides work without a catalogue

def test_purl_shared_by_two_products_maps_to_both():
    idx = index(product("a", "A", ["pkg:npm/shared"]), product("b", "B", ["pkg:npm/shared"]))
    assert idx.resolve("npm:shared") == [Match("A", "a"), Match("B", "b")]  # sorted by slug

def test_excluded_purls_are_ignored(monkeypatch):
    monkeypatch.setattr(catalog, "EXCLUDED_PURLS", frozenset({"npm:client-lib"}))
    assert index(product("x", "X", ["pkg:npm/client-lib"])).resolve("npm:client-lib") == []

@pytest.mark.parametrize("body", [b"not json", b'{"result": 5}', b'{"result": [{"name": "x"}]}'])
def test_bad_payload_raises(body):
    with pytest.raises(ApiUnavailable): parse_products(body)
```

- [ ] **Step 3: Run** `uv run pytest tests/test_catalog.py -v` — expect FAIL (`ModuleNotFoundError: eolchecker.catalog`).

- [ ] **Step 4: Implement** `catalog.py`, `OVERRIDES`, `Context.index`. `purl_key`: only types `npm`, `maven`, `composer`, `nuget`; strip `#…`, then `?…`, then `@version` (on the still-encoded string, so `%40` isn't mistaken for a version), then percent-decode and lowercase. `PurlIndex.resolve`: if the key is in `OVERRIDES` return the single override match (`COMPONENTS[component]` as product); else matches from the index sorted by slug; keys in `EXCLUDED_PURLS` are never indexed. Products missing `identifiers` just have no purls; products missing `name`/`releases` → `ApiUnavailable`.

- [ ] **Step 5: Run** `uv run pytest -v` — expect all PASS (existing tests untouched).

- [ ] **Step 6: Commit** `git commit -m "feat: purl index built from endoflife.date products"`

---

### Task 2: Fetch `/products/full` with an on-disk cache and config file

**Files:**
- Create: `src/eolchecker/cache.py`, `tests/test_cache.py`
- Modify: `src/eolchecker/api.py`, `tests/test_api.py`, `.gitignore` (add `.cache/`)

**Interfaces:**
- Consumes: `catalog.parse_products`, `catalog.Product`.
- Produces:
  - `api.FullResponse(not_modified: bool, body: bytes, etag: str | None)` (frozen)
  - `EolClient.products_full(etag: str | None = None) -> FullResponse` — `GET {BASE_URL}/products/full`, sends `If-None-Match` when `etag` given; 200 → body+`ETag` header; 304 → `not_modified=True, body=b""`; other status or `httpx.HTTPError` → `ApiUnavailable`. Remove `EolClient.releases()` and its tests (replace them with the tests below; keep the redirect test).
  - `cache.checkout_root() -> Path | None` — `Path(__file__).resolve().parents[2]` if it holds `pyproject.toml` and `src/eolchecker`, else None.
  - `cache.user_cache_dir() -> Path` — macOS `~/Library/Caches/eolchecker`; otherwise `$XDG_CACHE_HOME/eolchecker` or `~/.cache/eolchecker`.
  - `cache.default_cache_dir(warn: Callable[[str], None]) -> Path` — `eolchecker.toml` `cache_dir` (relative to checkout) → `<checkout>/.cache` → `user_cache_dir()`.
  - `cache.load_catalog(client, cache_dir: Path, *, refresh: bool, warn: Callable[[str], None]) -> list[Product]` — raises `ApiUnavailable` when there is no usable data.
  - Cache files in `cache_dir`: `products-full.json` (raw body) and `products-full.meta.json` (`{"etag": ..., "fetched": "<ISO-8601 UTC>"}`).

- [ ] **Step 1: Write the failing tests** (`tests/test_api.py` with `httpx.MockTransport` as today; `tests/test_cache.py` with a fake client recording the `etag` it was called with):

```python
# test_api.py
def test_products_full_200_returns_body_and_etag(): ...  # body == payload bytes, etag == '"abc"', not_modified False
def test_products_full_sends_if_none_match(): ...         # request.headers["If-None-Match"] == '"abc"'
def test_products_full_304(): ...                         # not_modified True
@pytest.mark.parametrize("status", [404, 500])
def test_products_full_error_status_raises(status): ...
def test_products_full_connect_error_raises(): ...

# test_cache.py
def test_first_run_downloads_and_writes_cache(tmp_path):
    client = RecordingClient(FullResponse(False, payload(product("php", "PHP")), '"e1"'))
    assert [p.slug for p in load_catalog(client, tmp_path, refresh=False, warn=print)] == ["php"]
    assert client.etags == [None]
    assert json.loads((tmp_path / "products-full.meta.json").read_text())["etag"] == '"e1"'

def test_second_run_sends_etag_and_uses_cache_on_304(tmp_path): ...   # etags == ['"e1"'], same products
def test_refresh_ignores_etag(tmp_path): ...                           # refresh=True → etags == [None]
def test_network_down_uses_cache_and_warns(tmp_path):
    # seed cache with fetched "2026-11-09T10:00:00+00:00"; client raises ApiUnavailable
    # → products returned; warnings == ["endoflife.date unreachable; using data from 2026-11-09"]
def test_network_down_without_cache_raises(tmp_path): ...
def test_corrupt_cache_counts_as_no_cache(tmp_path):
    (tmp_path / "products-full.json").write_text("{trunc"); (tmp_path / "products-full.meta.json").write_text("x")
    # client returns 200 → client.etags == [None], products parsed, cache rewritten
def test_unwritable_cache_dir_falls_back_to_user_cache(tmp_path, monkeypatch):
    # cache_dir is a file (mkdir fails); user_cache_dir monkeypatched to tmp_path/"user"
    # → products returned, file written under tmp_path/"user", one warning naming that folder
def test_config_cache_dir_relative_to_checkout(tmp_path, monkeypatch):
    # monkeypatch checkout_root → tmp_path; write eolchecker.toml 'cache_dir = "data"' → default_cache_dir == tmp_path/"data"
def test_default_cache_dir_is_checkout_dot_cache(tmp_path, monkeypatch): ...
def test_no_checkout_uses_user_cache_dir(monkeypatch): ...
def test_broken_config_warns_and_uses_default(tmp_path, monkeypatch): ...
```

- [ ] **Step 2: Run** `uv run pytest tests/test_api.py tests/test_cache.py -v` — expect FAIL.

- [ ] **Step 3: Implement.** `load_catalog` flow: read cache (body must parse with `parse_products`, meta must be valid JSON; otherwise treat as absent) → call `client.products_full(None if refresh or no cache else etag)` → on 304 with cache: update `fetched`, return cached products; on 200: parse, write both files (on `OSError` retry in `user_cache_dir()` and `warn(f"Couldn't write cache in {dir}; using {user_dir}")`; a second failure only warns), return; on `ApiUnavailable`: with cache → `warn(f"endoflife.date unreachable; using data from {fetched date YYYY-MM-DD}")`, return cached; without → re-raise. A 304 without a cache is an `ApiUnavailable`.

- [ ] **Step 4: Run** `uv run pytest -v` — `tests/test_rows.py` and `tests/test_cli.py` still use `releases()` fakes; they keep passing until Tasks 3 and 10 because those fakes don't depend on `EolClient`. Expect all PASS.

- [ ] **Step 5: Commit** `git commit -m "feat: fetch all products once, cached with ETag"`

---

### Task 3: Dependencies in the model, and rows per product

**Files:**
- Modify: `src/eolchecker/models.py`, `src/eolchecker/rows.py`, `tests/test_rows.py` (rewrite against `PurlIndex`)

**Interfaces:**
- Consumes: `PurlIndex.resolve`, `PurlIndex.releases`, `Match`.
- Produces:
  - `models.Dependency(key: str, name: str, version: str | None, display: str | None, source: Path, via_maven: bool = False)` (frozen). `name` is what the Dependencies column shows (npm/composer/nuget package name as written; Maven artifactId).
  - `DetectResult.dependencies: list[Dependency]` (default empty; `extend` includes it).
  - `Finding.origin: str = ""` (new last field) and `finding(component, version, display, source, via_maven=False, origin="")`.
  - `rows.Row(component: str, dependencies: tuple[str, ...], version: str, found_in: str, end_of_support: str, latest: str, status: str)`
  - `rows.build_rows(findings: list[Finding], dependencies: list[Dependency], index: PurlIndex) -> list[Row]`
  - `rows.untracked_by_file(dependencies: list[Dependency], index: PurlIndex) -> dict[Path, list[str]]`

- [ ] **Step 1: Write the failing tests** (rewrite `tests/test_rows.py`; keep the existing assertions for EOL/major-only/no-EOL/latest-tidy/via-Maven, now driven by `index(product(...))`):

```python
BOOT = product("spring-boot", "Spring Boot", ["pkg:maven/org.springframework.boot/spring-boot-starter-web",
               "pkg:maven/org.springframework.boot/spring-boot-starter-test"],
               [rel("3.4", "2024-11-21", False, "2025-12-31", "3.4.1"), rel("3.2", "2023-11-23", True, "2024-11-23", "3.2.12"),
                rel("4.1", "2026-06-30", False, "2027-07-31", "4.1.2")])
WEB = "maven:org.springframework.boot/spring-boot-starter-web"; TEST = "maven:org.springframework.boot/spring-boot-starter-test"
POM = Path("backend/pom.xml")

def test_one_row_per_product_lowest_version_wins():
    deps = [Dependency(WEB, "spring-boot-starter-web", "3.2.0", "3.2.0", POM),
            Dependency(TEST, "spring-boot-starter-test", "3.4.1", "3.4.1", POM)]
    assert build_rows([], deps, index(BOOT)) == [Row("Spring Boot", ("spring-boot-starter-test", "spring-boot-starter-web"),
        "3.2.0 (also 3.4.1)", "backend/pom.xml", "2024-11-23", "4.1.2", "END OF LIFE")]

def test_same_versions_show_once(): ...            # both 3.4.1 → version "3.4.1"
def test_versionless_dependency_joins_row(): ...   # WEB version None + finding("Spring Boot", "3.4.1", "3.4.1", POM, origin="spring-boot-starter-parent (parent)")
    # → one row, dependencies ("spring-boot-starter-parent (parent)", "spring-boot-starter-web"), version "3.4.1"
def test_versionless_group_without_version_is_dropped(): ...   # no finding, all None → []
def test_same_package_twice_listed_once(): ...     # two Dependency with same key/name → dependencies has the name once
def test_runtime_findings_stay_one_row_each():     # .NET net6.0 and net8.0 in the same csproj → two rows (no merging)
def test_runtime_merges_with_matching_package_group(): ...  # exactly one finding for (file, product) + deps → one row
def test_two_products_for_one_dependency_give_two_rows(): ...
def test_unknown_cycle_is_unknown_version(): ...   # status "unknown version", end_of_support "—"
def test_override_product_missing_from_catalogue_is_not_tracked(): ...  # finding("React", ...) with empty index → status "not tracked", latest "—"
def test_untracked_by_file():
    deps = [Dependency("maven:org.projectlombok/lombok", "lombok", "1.18.30", "1.18.30", POM),
            Dependency("maven:org.projectlombok/lombok", "lombok", None, None, POM), Dependency(WEB, "spring-boot-starter-web", "3.4.1", "3.4.1", POM)]
    assert untracked_by_file(deps, index(BOOT)) == {POM: ["lombok"]}
def test_sorted_by_file_then_component_order_then_label(): ...  # within a file: COMPONENTS order first, then others alphabetically by label
```

- [ ] **Step 2: Run** `uv run pytest tests/test_rows.py -v` — expect FAIL.

- [ ] **Step 3: Implement.** Grouping, as decided in the spec:
  1. Each dependency → `index.resolve(dep.key)`; none → untracked; otherwise one group entry per match, keyed `(source, product)`.
  2. Each finding is its own row candidate. If exactly one finding has the same `(source, product)` as a group, merge the group into it; otherwise the group becomes its own row (component = `Match.component`).
  3. Row version: lowest normalised version (compare as int tuples) among the finding and the group's versioned deps; Version column = its display, plus ` (also a, b)` with the other distinct displays in ascending order. A row with no version at all is dropped.
  4. Dependencies: the finding's `origin` (if any) first, then distinct dep names sorted.
  5. `(via Maven)` suffix if the finding or any versioned dep in the row is `via_maven`.
  6. Releases from `index.releases(product)`; None → status `not tracked`; no cycle match → `unknown version`.

- [ ] **Step 4: Run** `uv run pytest -v`. `report.py` and `cli.py` still call the old shapes: update `report.render` minimally to print the new `Dependencies` column (joined with `", "`) and `cli.main` to call `build_rows(result.findings, result.dependencies, <index>)`; full CLI changes come in Task 9. Expect all PASS except CLI tests using `releases()` fakes — update those fakes to build a `PurlIndex` via a temporary helper in `cli` (`_index_from_client`) **or** mark them `xfail(reason="rewired in Task 10")`; choose xfail, and Task 9 removes the marks.

- [ ] **Step 5: Commit** `git commit -m "feat: one row per product with matched dependencies"`

---

### Task 4: npm detector reports every dependency

**Files:**
- Modify: `src/eolchecker/detectors/npm.py`, `tests/detectors/test_npm.py`

**Interfaces:**
- Consumes: `Dependency`, `dep_key`, `ctx.index.resolve`, `Finding.origin`.
- Produces: `NpmDetector` returns `DetectResult(findings=[Node.js…], dependencies=[…], unrecognised=[…])`; `detectors/_util.gaps_for(dependencies: list[Dependency], index: PurlIndex, path: Path, ctx: Context) -> list[Unrecognised]` — the sibling-coverage gap rule below, reused by Composer, NuGet.

- [ ] **Step 1: Write the failing tests.** Change the existing Angular/AngularJS/React/Next tests to assert `dependencies` instead of `findings` (that's the intended change: they're now packages resolved by the override map). E.g.

```python
def test_angular_from_package_json_without_lock(write_files):
    root = write_files({"frontend/package.json": pkg({"@angular/core": "^16.2.0"})})
    assert run(root, "frontend/package.json").dependencies == [
        Dependency("npm:@angular/core", "@angular/core", "16.2.0", "^16.2.0", Path("frontend/package.json"))]

def test_every_section_is_read(write_files): ...   # dependencies, devDependencies, peerDependencies → one Dependency each, in that order
def test_untracked_with_unreadable_version_is_silent(write_files): ...  # {"left-pad": "git+https://…"} → Dependency(version None), unrecognised == []
def test_tracked_with_unreadable_version_is_a_gap(write_files): ...     # @angular/core "latest" → unrecognised ["couldn't read the Angular version"] (existing test_latest_tag_is_unrecognised)
def test_sibling_version_covers_unreadable_one(write_files):
    # idx with product angular purls @angular/core and @angular/common; {"@angular/core": "16.2.0", "@angular/common": "file:../x"}
    # → no unrecognised; both dependencies present
def test_node_engines_origin(write_files): ...      # Finding origin "engines.node"; .nvmrc → ".nvmrc"; .node-version → ".node-version"
def test_package_json_without_dependencies_is_silent(write_files): ...  # renamed from test_package_json_without_frameworks_is_silent
```
Lock-file tests keep their inputs; assert on the dependency's version.

- [ ] **Step 2: Run** `uv run pytest tests/detectors/test_npm.py -v` — expect FAIL.

- [ ] **Step 3: Implement.** Remove `PACKAGES` (now `models.OVERRIDES`). For each name in `DEP_SECTIONS`, in order, emit one `Dependency` (version from `_Lock.version`, else `lowest(declared)`; display as today). Gap rule: tracked (`ctx.index.resolve(key)` non-empty) and no version, and no other dependency in this file maps to the same product with a version → `gap(path, ctx, match.component)`.

- [ ] **Step 4: Run** `uv run pytest -v` — expect PASS.

- [ ] **Step 5: Commit** `git commit -m "feat: npm detector reports every direct dependency"`

---

### Task 5: Composer detector reports every dependency

**Files:**
- Modify: `src/eolchecker/detectors/composer.py`, `tests/detectors/test_composer.py`

**Interfaces:**
- Consumes: as Task 4, including `gaps_for`.

- [ ] **Step 1: Write the failing tests.** Laravel/Symfony tests assert `dependencies`. New:

```python
def test_require_and_require_dev(write_files): ...   # {"require": {"monolog/monolog": "^3.0"}, "require-dev": {"phpunit/phpunit": "^10.5"}} → two Dependency
def test_platform_packages_skipped(write_files): ... # "php", "ext-json", "lib-curl", "composer-plugin-api" → no Dependency (names without "/")
def test_php_origin(write_files): ...                # config.platform.php → origin "config.platform.php"; else "require.php"
def test_symfony_both_packages_one_dependency_each(write_files): ...  # framework-bundle + http-kernel → two Dependency (rows merge them later)
```

- [ ] **Step 2: Run** `uv run pytest tests/detectors/test_composer.py -v` — FAIL.
- [ ] **Step 3: Implement** (remove `PACKAGES`; skip names without `/`; versions from `composer.lock` else `lowest`).
- [ ] **Step 4: Run** `uv run pytest -v` — PASS.
- [ ] **Step 5: Commit** `git commit -m "feat: composer detector reports every direct dependency"`

---

### Task 6: NuGet packages and .NET origins

**Files:**
- Create: `src/eolchecker/detectors/nuget.py`, `tests/detectors/test_nuget.py`
- Modify: `src/eolchecker/detectors/dotnet.py` (origin only), `src/eolchecker/detectors/__init__.py` (register `NugetDetector`), `tests/detectors/test_dotnet.py`

**Interfaces:**
- Consumes: `gaps_for`, `dep_key("nuget", id)`, `dotnet._local`, `dirs_up`.
- Produces: `NugetDetector` — `applies_to`: `PROJECT_SUFFIXES` or `packages.config`.

- [ ] **Step 1: Write the failing tests:**

```python
def test_package_reference_attribute_and_element(write_files): ...
    # <PackageReference Include="Newtonsoft.Json" Version="13.0.3" /> and <PackageReference Include="Serilog"><Version>3.1.1</Version></PackageReference>
    # → [Dependency("nuget:newtonsoft.json", "Newtonsoft.Json", "13.0.3", "13.0.3", src), Dependency("nuget:serilog", "Serilog", "3.1.1", "3.1.1", src)]
def test_central_package_management(write_files): ...   # versionless PackageReference + Directory.Packages.props <PackageVersion Include Version> one folder up
def test_version_override_wins(write_files): ...        # VersionOverride attribute beats PackageVersion
def test_range_uses_lowest_bound(write_files): ...      # "[1.2,2.0)" → "1.2", display "[1.2,2.0)"
def test_packages_config(write_files): ...              # <package id="EntityFramework" version="6.4.4" /> → Dependency
def test_tracked_without_version_is_a_gap(write_files): ...
def test_broken_xml_unrecognised(write_files): ...
def test_registered(): ...
# test_dotnet.py: origins "TargetFramework", "TargetFrameworks", "TargetFrameworkVersion", "global.json"
```

- [ ] **Step 2: Run** `uv run pytest tests/detectors/test_nuget.py tests/detectors/test_dotnet.py -v` — FAIL.
- [ ] **Step 3: Implement.** Parse XML from bytes (as `dotnet.py`), ignore namespaces. `Directory.Packages.props`: nearest from the project folder up to `ctx.root`. `$(…)` in versions is not resolved → version None.
- [ ] **Step 4: Run** `uv run pytest -v` — PASS.
- [ ] **Step 5: Commit** `git commit -m "feat: read NuGet package references"`

---

### Task 7: Maven detector reports every dependency and plugin

**Files:**
- Modify: `src/eolchecker/detectors/maven.py`, `tests/detectors/test_maven.py`, `tests/detectors/test_maven_fallback.py`

**Interfaces:**
- Consumes: `Dependency`, `dep_key("maven", f"{group}/{artifact}")`, `ctx.index`.
- Produces:
  - `SPECIAL_SLUGS = frozenset({"spring-boot", "spring-framework", "hibernate-orm", "tomcat"})` — products whose gaps the existing special-case code already reports.
  - `read_pom(pom_xml, source, parent_props, *, check_java, inherited=None, index=None, parent_products=frozenset(), parent_managed=None) -> PomReading` (new keywords default so existing calls keep working).
  - `PomReading` gains `products: set[str]` (slugs this pom reports with a version, from findings and dependencies, plus `parent_products`) and `managed: dict[str, str]` (dep key → resolved version from this pom's and its parents' `<dependencyManagement>` / `<pluginManagement>`).
  - `_parent_chain(path, text, root, index, depth=0)` returns `(props, inherited, products, managed)`.
  - Gap entries in `PomReading.gaps` for generic dependencies use the dep key as their first element, so `_after_direct_read` can fill them.
  - Origins: Spring Boot from parent → `"spring-boot-starter-parent (parent)"`, from BOM → `"spring-boot-dependencies"`; Java → the property name used (`maven.compiler.release` / `maven.compiler.source` / `java.version`) or `"maven-compiler-plugin"`; Spring Framework from BOM → `"spring-framework-bom"`; Tomcat from property → `"tomcat.version"`; others from a dependency → its artifactId.

- [ ] **Step 1: Write the failing tests:**

```python
BOOT = product("spring-boot", "Spring Boot", ["pkg:maven/org.springframework.boot/spring-boot-starter-web"])
JACKSON = product("jackson-databind", "Jackson Databind", ["pkg:maven/com.fasterxml.jackson.core/jackson-databind"])

def run_idx(root, rel="pom.xml", *products, use_maven=False):
    return MavenDetector().detect(root / rel, Context(root, use_maven=use_maven, index=index(*products)))

def test_every_dependency_and_plugin_is_reported(write_files): ...
    # lombok 1.18.30 (scope provided), junit-jupiter 5.10.0 (scope test), plugin jacoco-maven-plugin 0.8.11 → three Dependency
def test_version_from_own_dependency_management(write_files): ...   # versionless jackson + managed 2.15.2 → Dependency version "2.15.2"
def test_managed_entries_alone_are_not_dependencies(write_files): ... # only <dependencyManagement> jackson → dependencies == []
def test_starters_join_boot_row_without_gap(write_files):
    body = BOOT_PARENT + "<properties><java.version>17</java.version></properties><dependencies>" + \
        dep("org.springframework.boot", "spring-boot-starter-web") + "</dependencies>"
    result = run_idx(write_files({"pom.xml": pom(body)}), "pom.xml", BOOT)
    assert result.unrecognised == []
    assert [(d.name, d.version) for d in result.dependencies] == [("spring-boot-starter-web", None)]
def test_tracked_versionless_is_a_gap(write_files): ...   # Boot parent + versionless jackson → "Jackson Databind version is set by Spring Boot"
def test_untracked_versionless_is_silent(write_files): ... # versionless lombok → no gap
def test_child_covered_by_parent_product_has_no_row(write_files): ...
    # extends test_child_inherits_from_in_repo_parent with index(BOOT): child dependencies contain no versioned spring-boot entry, no gap, no Maven call (runner fake asserts not called with use_maven=True)
def test_child_gets_version_from_parent_dependency_management(write_files): ...
    # parent <dependencyManagement> jackson 2.15.2; child versionless jackson → Dependency version "2.15.2", no gap, Maven not run
def test_origins(write_files): ...   # Spring Boot finding origin "spring-boot-starter-parent (parent)", Java "java.version"
# test_maven_fallback.py
def test_fallback_fills_generic_gap(write_files, monkeypatch): ...
    # versionless jackson under a company parent; fake effective pom has jackson 2.17.0 → Dependency version "2.17.0", via_maven True, no unrecognised
```
Existing tests stay as they are (they use `Context` without an index, so generic dependencies are untracked and add no gaps); add `.dependencies` assertions only where noted above.

- [ ] **Step 2: Run** `uv run pytest tests/detectors/test_maven.py tests/detectors/test_maven_fallback.py -v` — FAIL.

- [ ] **Step 3: Implement.** After the special cases in `read_pom`, two passes over `dependency` and `plugin` coords: first resolve each version (own value → own managed → `parent_managed`; `${…}` via props; normalise), then decide per coord:
  - versioned → `Dependency` with version;
  - untracked → `Dependency(version=None)`;
  - tracked, every matched slug in `parent_products` → skip (the parent's row covers it);
  - tracked, slug in `SPECIAL_SLUGS` or a sibling in this pom has a version for the slug → `Dependency(version=None)`;
  - otherwise → `Dependency(version=None)` plus gap: unresolved property → `couldn't resolve ${x}`; no version → `"<component> version is set by Spring Boot"` if Boot-managed else `"<component> version is set by a parent pom or BOM"`.
  `_after_direct_read`: fill generic gaps from the effective pom's versioned dependencies with the same key (`via_maven=True`), replacing the versionless entry; unfilled gaps stay as today.

- [ ] **Step 4: Run** `uv run pytest -v` — PASS.
- [ ] **Step 5: Commit** `git commit -m "feat: maven detector reports every dependency and plugin"`

---

### Task 8: Table, untracked section and CSV

**Files:**
- Modify: `src/eolchecker/report.py`, `tests/test_report.py` (create)

**Interfaces:**
- Consumes: `Row`, `Unrecognised`.
- Produces:
  - `render(repo_name, rows, unrecognised, console, untracked: dict[Path, list[str]] | None = None) -> None` — prints `Not on endoflife.date:` then `  <file>: a, b` per file (sorted by path) after "Not recognised", only when `untracked` is not None and non-empty.
  - `write_csv(path: Path, rows, unrecognised, untracked: dict[Path, list[str]] | None = None) -> None` — raises `OSError`.
  - `STATUS_STYLE` adds `"unknown version": "dim"`, `"not tracked": "dim"`.

- [ ] **Step 1: Write the failing tests:**

```python
def test_table_has_dependencies_column(): ...   # header order exactly as Global Constraints; cell "spring-boot-starter-test, spring-boot-starter-web"
def test_untracked_section(): ...                # "Not on endoflife.date:" and "  backend/pom.xml: lombok, slf4j-api"
def test_untracked_hidden_when_none(): ...
def test_csv(tmp_path):
    write_csv(tmp_path / "r.csv", [ROW], [Unrecognised(Path("a/pom.xml"), "couldn't resolve ${x}")], {Path("a/pom.xml"): ["lombok"]})
    assert list(csv.reader((tmp_path / "r.csv").open(encoding="utf-8", newline=""))) == [
        ["Component", "Dependencies", "Version", "Found in", "End of support", "Latest", "Status"],
        ["Spring Boot", "spring-boot-starter-test; spring-boot-starter-web", "3.2.0 (also 3.4.1)", "backend/pom.xml", "2024-11-23", "4.1.2", "END OF LIFE"],
        ["", "couldn't resolve ${x}", "", "a/pom.xml", "", "", "not recognised"],
        ["", "lombok", "", "a/pom.xml", "", "", "not tracked"],
    ]
def test_csv_without_untracked_has_no_not_tracked_rows(tmp_path): ...
```

- [ ] **Step 2: Run** `uv run pytest tests/test_report.py -v` — FAIL.
- [ ] **Step 3: Implement** with `csv.writer` (UTF-8, `newline=""`); "—" cells are written as empty strings.
- [ ] **Step 4: Run** `uv run pytest -v` — PASS.
- [ ] **Step 5: Commit** `git commit -m "feat: dependencies column, untracked section and CSV export"`

---

### Task 9: CLI wiring, options and end-to-end test

**Files:**
- Modify: `src/eolchecker/cli.py`, `tests/test_cli.py`, `tests/test_end_to_end.py`

**Interfaces:**
- Consumes: `load_catalog`, `default_cache_dir`, `PurlIndex`, `Context(index=…)`, `build_rows`, `untracked_by_file`, `render`, `write_csv`, `tests/fakes.FakeClient` (returns a fixed `FullResponse`, or raises `ApiUnavailable`).
- Produces: `main(argv=None, client=None, detectors=None, cache_dir: Path | None = None) -> int`.

- [ ] **Step 1: Write the failing tests** (rewrite the `releases()` fakes to `FakeClient(payload(...))`, pass `cache_dir=tmp_path / "cache"` in every test, remove Task 3's xfail marks):

```python
def test_prints_table(...): ...            # as today plus "Dependencies" header
def test_api_down_without_cache_exit_1(...): ...   # stderr "Couldn't fetch end-of-life dates from endoflife.date: timed out"
def test_api_down_with_cache_warns_and_prints(...): ...
def test_nothing_found_exit_0(...): ...    # "No tracked dependencies found in <root>"
def test_show_untracked(...): ...          # StubDetector returns an untracked Dependency → "Not on endoflife.date:" only with --show-untracked
def test_csv_written(...): ...             # --csv out.csv → file exists, header row correct, table still printed, exit 0
def test_csv_to_missing_folder_exit_1(...): ...  # --csv nope/out.csv → stderr mentions the path, table still printed, exit 1
def test_refresh_ignores_etag(...): ...    # second run with --refresh → client saw etag None
def test_detectors_get_the_index(...): ... # StubDetector records ctx.index.resolve("npm:x") non-empty when catalogue has pkg:npm/x
```
`tests/test_end_to_end.py`: pass `cache_dir=tmp_path / "cache"`; add `spring-boot-starter-web` (versionless) to the POM and assert `"spring-boot-starter-web"` in the output; replace `assert "unknown" not in out` with `assert "unknown version" not in out`.

- [ ] **Step 2: Run** `uv run pytest tests/test_cli.py -v` — FAIL.
- [ ] **Step 3: Implement.** Order: parse args → check path → `load_catalog(client or EolClient(), cache_dir or default_cache_dir(warn), refresh=args.refresh, warn=<print to stderr>)` (on `ApiUnavailable` → message, exit 1) → `scan(root, Context(root, use_maven=…, index=idx), detectors)` → `build_rows` → nothing to show? print `No tracked dependencies found in {root}` (still print the untracked section if requested) → `render` → `write_csv` if `--csv` (`OSError` → `Couldn't write {path}: {reason}` on stderr, exit 1). Update the parser description to "Check whether a repo's dependencies are past end-of-life."
- [ ] **Step 4: Run** `uv run pytest -v` — PASS. Then `EOLCHECKER_NETWORK=1 uv run pytest tests/test_end_to_end.py -v` — PASS.
- [ ] **Step 5: Smoke run** `uv run eolchecker . --no-maven --show-untracked` from the checkout → table/“No tracked dependencies” prints, `.cache/products-full.json` exists, `git status` doesn't show `.cache/`.
- [ ] **Step 6: Commit** `git commit -m "feat: wire catalogue, --csv, --show-untracked and --refresh into the CLI"`

---

### Task 10: README

**Files:**
- Modify: `README.md`, `pyproject.toml` (`description` → "Check whether a repo's dependencies are past end-of-life")

- [ ] **Step 1: Rewrite the README** with these sections, in order:
  - Intro: checks every direct dependency endoflife.date tracks, plus Java/Node.js/PHP/.NET.
  - **Install:** needs [uv](https://docs.astral.sh/uv/) (it fetches Python ≥ 3.11 if missing); optional Maven or a project `mvnw` for versions inherited from parent poms. `git clone …`, `cd eolchecker`, `uv sync`.
  - **Run:** `uv run eolchecker ~/code/some-repo` from the checkout; each option with one line (`--no-maven`, `--csv results.csv`, `--show-untracked`, `--refresh`); a short sample of the table (columns as in Global Constraints); the status meanings. Alternative: `uv tool install .` then `eolchecker …` (cache then in the user cache folder).
  - **Cache and config:** `.cache/products-full.json` in the checkout, re-checked every run (only downloaded again when endoflife.date has changed), cached copy used when offline; `eolchecker.toml` with `cache_dir = "…"`.
  - **What it checks:** dependencies matched by the package identifiers (purls) endoflife.date publishes; direct only (incl. dev/test/plugins), lock files only for exact versions; one row per product per file, lowest version; files read (add `packages.config`, `Directory.Packages.props`); not Gradle, Dockerfiles or CI configs.
  - **Development:** unchanged commands.
- [ ] **Step 2: Check** every command in the README runs as written (`uv sync`, `uv run eolchecker --help`, `uv run pytest`).
- [ ] **Step 3: Commit** `git commit -m "docs: install, run and what-it-checks for every product"`
