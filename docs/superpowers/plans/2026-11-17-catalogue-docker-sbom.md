# Catalogue matching, Docker and SBOM Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Check every directly declared dependency (npm, Maven, Composer, NuGet, Docker) against the full endoflife.date catalogue without hand-written package lists, add Docker/compose files with OS rows, and write an SBOM as CSV or Markdown.

**Architecture:** Detectors stop filtering and emit every declared `Dependency` (plus unchanged runtime `Finding`s for Java/Node.js/PHP/.NET). A cached copy of `/api/v1/products/full` (`catalogue.py`) feeds a `Matcher` (`matching.py`: exact purl, then three narrow rules) and OS detection from Docker tags. `rows.build_report` merges everything into table rows, SBOM rows and "Not recognised" lines; `sbom.py` formats; `cli.py` wires it.

**Tech Stack:** Python ≥3.11, uv, httpx, rich, pyyaml, pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-11-17-catalogue-docker-sbom-design.md` — read it first; this plan refers to its section numbers (§1–§7).

## Global Constraints

- No hand-written package or image names anywhere. Allowed fixed slugs: runtime products `eclipse-temurin`, `nodejs`, `php`, `dotnet`, `dotnetfx`; OS products `debian`, `ubuntu`, `alpine-linux`.
- Detectors never touch the catalogue or printing. `main()` takes the catalogue loader and detectors as parameters so tests use fakes.
- No network in unit tests. Only `tests/test_end_to_end.py` may hit the network, behind `EOLCHECKER_NETWORK=1`.
- One bad file or one API failure never crashes the run.
- Status strings are exactly `END OF LIFE`, `supported`, `no EOL date`, `version not found`.
- SBOM columns, in order: `Ecosystem, Name, Version, Found in, Product, End of support, Status`. Ecosystem values: `npm`, `Maven`, `Composer`, `NuGet`, `Docker`, `Runtime`.
- Run tests with `uv run pytest`. Commit after every task.

## Review Focus

1. **A Spring Boot pom run with `--no-maven`** (parent `spring-boot-starter-parent` 3.2.0, ten versionless starters) should print one clean Spring Boot 3.2 row and no "Not recognised" lines. Pinned in Task 9 (`test_versionless_members_do_not_decide`).
2. **A Symfony 6.4 project that also requires `symfony/polyfill-mbstring` 1.x and `symfony/flex` 2.8** should show Symfony 6.4. Flex must not show "END OF LIFE" in the SBOM. Pinned in Task 9 (`test_rule_matches_use_most_common_version`, `test_sbom_rule_match_outside_chosen_cycle_has_blank_status`).
3. **An offline run with an old cached catalogue** should still work and warn on stderr. A corrupt cache file should count as no cache. Pinned in Task 1 (`test_stale_cache_used_when_offline`, `test_corrupt_cache_ignored`).
4. **Multi-stage Dockerfiles with `--platform` and `ARG` defaults**, for example `ARG NODE=18` / `FROM --platform=$BUILDPLATFORM node:${NODE}-bullseye AS build` / `FROM build`: the second `FROM` is a stage, not an image. Pinned in Task 8 (`test_multi_stage_platform_and_arg`).
5. **Registry ports in image names**, for example `localhost:5000/app:1.2`: the port is not a tag. Pinned in Task 8 (`test_registry_port_is_not_a_tag`).

---

## File structure

| File | Responsibility |
|---|---|
| `src/eolchecker/catalogue.py` (new) | `Release`, `Product`, `Catalogue`, `parse_catalogue`, `load_catalogue` (download + 24 h cache + stale fallback), `ApiUnavailable` |
| `src/eolchecker/matching.py` (new) | purl building/normalising, `Matcher` (exact + 3 rules), `os_from_tag` |
| `src/eolchecker/detectors/docker.py` (new) | Dockerfile and compose reading |
| `src/eolchecker/sbom.py` (new) | `to_csv`, `to_markdown`, `write_sbom` |
| `src/eolchecker/models.py` | `Dependency`, `DetectResult.dependencies`, `RUNTIMES` replaces `COMPONENTS` |
| `src/eolchecker/rows.py` | `build_report` replaces `build_rows` |
| `src/eolchecker/detectors/{npm,composer,dotnet,maven}.py` | emit every declared dependency; framework logic removed |
| `src/eolchecker/cli.py`, `report.py` | `--sbom`, catalogue loading, new status |
| `src/eolchecker/api.py`, `tests/test_api.py` | deleted in Task 11 |
| `tests/catalogue_fixture.py` (new) | small hand-built catalogue used by many tests |

---

### Task 1: Catalogue download, cache and parsing

**Files:**
- Create: `src/eolchecker/catalogue.py`, `tests/catalogue_fixture.py`, `tests/test_catalogue.py`
- Modify: `src/eolchecker/api.py` (import `Release`, `ApiUnavailable` from `catalogue` instead of defining them)

**Interfaces:**
- Produces:
  - `Release(name: str, release_date: str, is_eol: bool, eol_from: str | None, latest: str | None, codename: str | None = None)` (frozen dataclass, moved here)
  - `Product(name: str, label: str, aliases: tuple[str, ...], purls: tuple[str, ...], releases: tuple[Release, ...])` (frozen)
  - `class Catalogue`: `__init__(products: dict[str, Product])`, `product(slug: str) -> Product | None`, `products() -> list[Product]`
  - `parse_catalogue(data: dict) -> Catalogue`, which raises `ApiUnavailable` on a bad shape
  - `ApiUnavailable(Exception)`
  - `FULL_URL = "https://endoflife.date/api/v1/products/full"`, `MAX_AGE_SECONDS = 24 * 3600`
  - `default_cache_file() -> Path`: macOS `~/Library/Caches/eolchecker/products-full.json`; elsewhere `$XDG_CACHE_HOME/eolchecker/products-full.json`, falling back to `~/.cache/eolchecker/products-full.json`
  - `load_catalogue(cache_file: Path | None = None, http: httpx.Client | None = None, now: float | None = None) -> Catalogue`
  - `tests/catalogue_fixture.py`: `FULL: dict` (API-shaped `{"result": [...]}`) and `catalogue() -> Catalogue`

- [ ] **Step 1: Write `tests/catalogue_fixture.py`**

  Use two helpers that build API-shaped dicts:
  - `p(name, label, purls=(), aliases=(), releases=())` builds `{"name","label","aliases","identifiers":[{"type":"purl","id":…}],"releases":[…]}`
  - `r(name, date, is_eol, eol, latest, codename=None)` builds `{"name","releaseDate","isEol","eolFrom","latest":{"name":latest},"codename"}`

  The fixture contents. Every later test relies on these exact values:

  | slug | label | purls | aliases | releases (name, date, isEol, eolFrom, latest, codename) |
  |---|---|---|---|---|
  | spring-boot | Spring Boot | `pkg:maven/org.springframework.boot/spring-boot`, `pkg:maven/org.springframework.boot/spring-boot-starter-web` | | 4.0 2025-11-20 F 2026-12-31 4.0.1; 3.2 2023-11-23 T 2024-12-31 3.2.12 |
  | spring-framework | Spring Framework | `pkg:maven/org.springframework/spring-core` | | 6.2 2024-11-14 F 2026-06-30 6.2.1; 5.3 2020-10-27 T 2024-08-31 5.3.39 |
  | hibernate-orm | Hibernate ORM | `pkg:maven/org.hibernate.orm/hibernate-core`, `pkg:maven/org.hibernate/hibernate-core` | | 6.6 2024-08-08 F 2026-08-08 6.6.3; 5.6 2021-08-05 T 2023-11-01 5.6.15 |
  | jquery | jQuery | `pkg:maven/org.webjars/jquery`, `pkg:npm/jquery` | | 3 2016-06-09 F None 3.7.1 |
  | jquery-ui | jQuery UI | `pkg:maven/org.webjars/jquery-ui` | | 1.13 2021-10-07 F None 1.13.3 |
  | angular | Angular | `pkg:npm/%40angular/core` | | 20 2025-05-28 F 2026-11-28 20.3.0; 16 2023-05-03 T 2024-11-08 16.2.12 |
  | react | React | `pkg:npm/react` | | 19 2024-12-05 F None 19.2.0; 17 2020-10-20 F None 17.0.2 |
  | laravel | Laravel | `pkg:composer/laravel/framework` | | 12 2025-02-24 F 2027-02-24 12.1.0; 10 2023-02-14 T 2025-02-04 10.48.0 |
  | symfony | Symfony | (none) | | 6.4 2023-11-29 F 2027-11-30 6.4.20; 2.8 2015-11-30 T 2018-11-30 2.8.52 |
  | dotnet | Microsoft .NET | `pkg:nuget/Microsoft.NETCore.App` | dotnetcore | 8 2023-11-14 F 2026-11-10 8.0.21; 6 2021-11-08 T 2024-11-12 6.0.36 |
  | dotnetfx | Microsoft .NET Framework | | | 4.8 2019-04-18 F None None |
  | nodejs | Node.js | `pkg:docker/library/node`, `pkg:docker/bitnami/node` | | 22 2024-04-24 F 2027-04-30 22.11.0; 18 2022-04-19 T 2025-04-30 18.20.5 |
  | php | PHP | | | 8.3 2023-11-23 F 2027-12-31 8.3.14; 8.1 2021-11-25 T 2025-12-31 8.1.31 |
  | eclipse-temurin | Eclipse Temurin | | temurin | 17 2021-09-14 F 2027-10-31 17.0.13 |
  | deno | Deno | `pkg:oci/deno?repository_url=ghcr.io/denoland` | | 2 2024-10-09 F None 2.1.4 |
  | debian | Debian | | | 12 2023-06-10 F 2026-06-10 12.8 Bookworm; 11 2021-08-14 T 2024-08-14 11.11 Bullseye |
  | ubuntu | Ubuntu | | ubuntu-linux | 22.04 2022-04-21 F 2027-04-01 22.04 "Jammy Jellyfish"; 18.04 2018-04-26 T 2023-05-31 18.04 "Bionic Beaver" |
  | alpine-linux | Alpine Linux | | alpine, alpinelinux | 3.22 2025-05-30 F 2027-05-01 3.22.2; 3.19 2023-12-07 T 2025-11-01 3.19.4 |

- [ ] **Step 2: Write failing tests in `tests/test_catalogue.py`**

  ```python
  def test_parse_fixture():
      cat = catalogue()
      boot = cat.product("spring-boot")
      assert boot.label == "Spring Boot"
      assert "pkg:maven/org.springframework.boot/spring-boot-starter-web" in boot.purls
      assert boot.releases[1] == Release("3.2", "2023-11-23", True, "2024-12-31", "3.2.12")
      assert cat.product("debian").releases[0].codename == "Bookworm"
      assert cat.product("nope") is None

  def test_bad_shape_raises():
      with pytest.raises(ApiUnavailable):
          parse_catalogue({"result": [{"name": "x"}]})

  def test_downloads_and_writes_cache(tmp_path):        # MockTransport returns FULL; asserts URL path /api/v1/products/full
      cache = tmp_path / "c" / "products-full.json"
      cat = load_catalogue(cache, http_returning(FULL), now=1000.0)
      assert cat.product("php") and json.loads(cache.read_text()) == FULL

  def test_fresh_cache_skips_network(tmp_path):         # cache mtime = now - 3600; transport raises if called
  def test_old_cache_is_refreshed(tmp_path):            # mtime = now - 25h; transport called once; file rewritten
  def test_stale_cache_used_when_offline(tmp_path, capsys):
      # mtime = now - 3 days; transport raises httpx.ConnectError
      assert load_catalogue(cache, failing_http(), now=now).product("php")
      assert "using a cached copy from 3 days ago" in capsys.readouterr().err
  def test_offline_without_cache_raises(tmp_path):      # pytest.raises(ApiUnavailable)
  def test_corrupt_cache_ignored(tmp_path):             # cache contains "{", offline → raises ApiUnavailable; online → refreshed
  def test_http_error_status_without_cache_raises(tmp_path)   # 500 → ApiUnavailable
  def test_default_cache_file_xdg(monkeypatch, tmp_path):     # sys.platform "linux", XDG_CACHE_HOME=tmp → tmp/eolchecker/products-full.json
  ```

- [ ] **Step 3: Run `uv run pytest tests/test_catalogue.py -v`.** Expected: FAIL (module not found).

- [ ] **Step 4: Implement `catalogue.py`.** Freshness uses the cache file's mtime (`os.utime` in tests). Use the same User-Agent as today (`eolchecker/0.1`), `follow_redirects=True`, `timeout=30`. The stale warning goes to stderr: `Couldn't reach endoflife.date ({reason}); using a cached copy from {age}.`, where age is `N days ago` if ≥ 1 day, otherwise `N hours ago`. If writing the cache fails, ignore it. In `api.py`, delete the `Release`/`ApiUnavailable` definitions and import them from `catalogue`.

- [ ] **Step 5: Run `uv run pytest`.** Expected: all pass, old suite included.

- [ ] **Step 6: Commit** `feat: endoflife.date catalogue with local cache`

---

### Task 2: Dependency model and matching

**Files:**
- Create: `src/eolchecker/matching.py`, `tests/test_matching.py`
- Modify: `src/eolchecker/models.py`

**Interfaces:**
- Consumes: `Catalogue`, `Product` (Task 1)
- Produces:
  - In `models.py`:
    ```python
    @dataclass(frozen=True)
    class Dependency:
        ecosystem: str            # "npm" | "Maven" | "Composer" | "NuGet" | "Docker"
        name: str                 # npm name; "group:artifact"; "vendor/pkg"; NuGet id; image ref without tag/digest
        version: str | None       # normalised for matching; None when unreadable
        display: str              # Version column text
        source: Path              # relative to scan root
        via_maven: bool = False
        missing: str | None = None  # short reason when version is None, e.g. "set by parent pom"
        tag: str | None = None      # Docker only: full tag, for OS rows
    ```
    `DetectResult.dependencies: list[Dependency]` (default empty), included in `extend`.
  - In `matching.py`:
    - `normalise_purl(purl: str) -> str`
    - `dependency_purl(dep: Dependency) -> str`
    - `docker_purl(image: str) -> str`
    - `is_official_image(image: str) -> bool`
    - `Match(product: str, by_rule: bool)` (frozen)
    - `class Matcher`: `__init__(catalogue: Catalogue)`, `match(dep: Dependency) -> Match | None`

- [ ] **Step 1: Write failing tests**

  ```python
  @pytest.mark.parametrize("raw, expected", [
      ("pkg:npm/%40angular/core", "pkg:npm/@angular/core"),
      ("pkg:npm/React@18.2.0", "pkg:npm/react"),
      ("pkg:maven/org.Foo/Bar@1.0?type=jar", "pkg:maven/org.Foo/Bar"),          # Maven keeps case
      ("pkg:nuget/Microsoft.NETCore.App", "pkg:nuget/microsoft.netcore.app"),
      ("pkg:oci/deno?repository_url=ghcr.io/denoland", "pkg:oci/deno?repository_url=ghcr.io/denoland"),
      ("pkg:docker/library/node?tag=18", "pkg:docker/library/node"),
  ])
  def test_normalise_purl(raw, expected): ...

  @pytest.mark.parametrize("image, expected", [
      ("node", "pkg:docker/library/node"),
      ("docker.io/library/node", "pkg:docker/library/node"),
      ("index.docker.io/bitnami/node", "pkg:docker/bitnami/node"),
      ("ghcr.io/denoland/deno", "pkg:oci/deno?repository_url=ghcr.io/denoland"),
      ("localhost:5000/app", "pkg:oci/app?repository_url=localhost:5000"),
  ])
  def test_docker_purl(image, expected): ...

  def test_official_image():
      assert is_official_image("php") and is_official_image("library/php") and is_official_image("docker.io/php")
      assert not is_official_image("myorg/php") and not is_official_image("ghcr.io/x/php")

  M = Matcher(catalogue())
  def dep(eco, name): return Dependency(eco, name, "1.0", "1.0", Path("f"))

  @pytest.mark.parametrize("eco, name, expected", [
      ("npm", "@angular/core", Match("angular", False)),
      ("npm", "React", Match("react", False)),
      ("Maven", "org.springframework.boot:spring-boot-starter-web", Match("spring-boot", False)),
      ("Maven", "org.springframework.boot:spring-boot-starter-parent", Match("spring-boot", True)),   # group rule
      ("Maven", "org.hibernate:hibernate-core", Match("hibernate-orm", False)),
      ("NuGet", "microsoft.netcore.app", Match("dotnet", False)),
      ("Composer", "laravel/framework", Match("laravel", False)),
      ("Composer", "symfony/http-kernel", Match("symfony", True)),                                    # vendor rule
      ("Docker", "node", Match("nodejs", False)),
      ("Docker", "ghcr.io/denoland/deno", Match("deno", False)),
      ("Docker", "php", Match("php", True)),                                                          # name rule
      ("Docker", "alpine", Match("alpine-linux", True)),                                              # alias
      ("Docker", "eclipse-temurin", Match("eclipse-temurin", True)),
  ])
  def test_matches(eco, name, expected): assert M.match(dep(eco, name)) == expected

  @pytest.mark.parametrize("eco, name", [
      ("Maven", "org.springframework.data:spring-data-jpa"),   # no prefix matching
      ("Maven", "org.webjars:bootstrap"),                      # ambiguous group (jquery, jquery-ui)
      ("Composer", "laravel/sanctum"),                         # Laravel has its own Composer purl
      ("Docker", "myorg/php"),                                 # name rule is official images only
      ("Docker", "registry.example.com/java-base"),
      ("npm", "left-pad"),
  ])
  def test_no_match(eco, name): assert M.match(dep(eco, name)) is None
  ```

- [ ] **Step 2: Run `uv run pytest tests/test_matching.py -v`.** Expected: FAIL.

- [ ] **Step 3: Add `Dependency` and `DetectResult.dependencies` to `models.py`.** Leave `COMPONENTS`/`finding` alone until Task 9.

- [ ] **Step 4: Implement `matching.py`.**
  - `normalise_purl`: split off `?qualifiers`. Keep only `repository_url`, and only for `pkg:docker`/`pkg:oci`. Cut `@version` from the last path segment, then percent-decode. Lower-case everything except the path of `pkg:maven`.
  - `docker_purl`: lower-case and strip a leading `docker.io/`, `index.docker.io/` or `registry-1.docker.io/`. If the first segment contains `.` or `:`, or is `localhost`, and there is more than one segment: `pkg:oci/<last>?repository_url=<rest>`. Otherwise prefix `library/` when there's no `/`, giving `pkg:docker/<ref>`.
  - `Matcher` builds its indexes once:
    - exact: `normalise_purl(purl)` → product
    - Maven group: group → set of products; keep only the groups with exactly one product
    - Composer vendor: for products with no `pkg:composer` purl, `name` and each alias, lower-cased → product
    - Docker names: `name` and each alias, lower-cased → product
  - Drop any name or alias claimed by two products.
  - `match` order: exact purl, then the ecosystem's rule (Maven group, Composer vendor, or Docker name when `is_official_image`). Rule hits return `by_rule=True`.

- [ ] **Step 5: Run `uv run pytest`.** Expected: all pass.

- [ ] **Step 6: Commit** `feat: match dependencies to endoflife.date products`

---

### Task 3: OS rows from Docker tags

**Files:**
- Modify: `src/eolchecker/matching.py`, `tests/test_matching.py`

**Interfaces:**
- Produces:
  - `OsHit(product: str, version: str, display: str)` (frozen)
  - `OsReading(hits: list[OsHit], missing: list[tuple[str, str]])`, where `missing` holds `(product slug, reason)`
  - `os_from_tag(tag: str, catalogue: Catalogue) -> OsReading`
  - Constants `ALPINE = "alpine-linux"`, `CODENAME_PRODUCTS = ("debian", "ubuntu")`

- [ ] **Step 1: Write failing tests**

  ```python
  @pytest.mark.parametrize("tag, hits", [
      ("18-alpine3.19", [OsHit("alpine-linux", "3.19", "3.19")]),
      ("18-bullseye", [OsHit("debian", "11", "11 (bullseye)")]),
      ("3.12-slim-Bookworm", [OsHit("debian", "12", "12 (bookworm)")]),
      ("17-jre-jammy", [OsHit("ubuntu", "22.04", "22.04 (jammy)")]),
      ("bookworm-slim", [OsHit("debian", "12", "12 (bookworm)")]),
      ("8.3-fpm", []),
      ("latest", []),
  ])
  def test_os_from_tag(tag, hits): assert os_from_tag(tag, catalogue()).hits == hits

  def test_unpinned_alpine():
      reading = os_from_tag("18-alpine", catalogue())
      assert reading.hits == [] and reading.missing == [("alpine-linux", "Alpine version not pinned")]
  ```

- [ ] **Step 2: Run the tests.** Expected: FAIL.

- [ ] **Step 3: Implement `os_from_tag`.** Split the tag on `-`, lower-case each part.
  - `alpine(\d+(?:\.\d+)*)` gives an Alpine hit.
  - Bare `alpine` gives a missing entry.
  - Otherwise compare against the first word of each release `codename` (lower-cased) of the `CODENAME_PRODUCTS`. A hit has `version` = the release name and `display` = `"{release} ({part})"`.
  - Ignore any other part.

- [ ] **Step 4: Run `uv run pytest`.** Expected: all pass.

- [ ] **Step 5: Commit** `feat: read the base OS from Docker image tags`

---

### Task 4: npm detector emits every dependency

**Files:**
- Modify: `src/eolchecker/detectors/npm.py`, `tests/detectors/test_npm.py`

**Interfaces:**
- Consumes: `Dependency` (Task 2)
- Produces: for each `package.json`, a `Dependency("npm", name, …)` for every name in `dependencies`, `devDependencies` and `peerDependencies`. The first section wins on duplicates. Node.js runtime findings are unchanged.

- [ ] **Step 1: Rewrite the framework tests to assert on `result.dependencies`.** Keep each test's fixture, and keep every lock-file and Node test as it is.
  - `test_angular_from_package_json_without_lock`: `Dependency("npm", "@angular/core", "16.2.0", "16.2.0", Path("package.json"))` is in `result.dependencies`.
  - `test_lockfile_wins` / `_v1` / `yarn` / `pnpm` / workspace tests: the same expected versions, now on the `Dependency`.
  - `test_angularjs_react_next_and_engines`: dependencies for `angular`, `react` and `next`, plus the Node.js finding.
  - `test_latest_tag_is_unrecognised` becomes `test_unreadable_version_is_kept_with_reason`: `Dependency("npm", "react", None, "latest", src, missing="'latest' isn't a version")`, and `result.unrecognised == []`.
  - `test_package_json_without_frameworks_is_silent` becomes `test_every_dependency_is_listed`: `{"dependencies": {"left-pad": "^1.3.0"}, "devDependencies": {"jest": "29.7.0"}}` gives two dependencies. `left-pad` has version `1.3.0` and display `^1.3.0`.

- [ ] **Step 2: Run `uv run pytest tests/detectors/test_npm.py -v`.** Expected: the rewritten tests FAIL.

- [ ] **Step 3: Implement.** Delete `PACKAGES`. Loop over every declared name, using the existing `_Lock.version` and `lowest` logic. An unreadable version gives `version=None`, `display=declared`, `missing=f"'{declared}' isn't a version"`. Skip non-string values silently.

- [ ] **Step 4: Run `uv run pytest`.** Expected: all pass.

- [ ] **Step 5: Commit** `feat(npm): list every declared dependency`

---

### Task 5: Composer detector emits every dependency

**Files:**
- Modify: `src/eolchecker/detectors/composer.py`, `tests/detectors/test_composer.py`

**Interfaces:**
- Produces: `Dependency("Composer", name, …)` for every key in `require` and `require-dev` that contains `/`. Platform packages (`php`, `ext-*`, `lib-*`, `composer-*`) have no `/`, so they're skipped. The PHP runtime finding is unchanged.

- [ ] **Step 1: Rewrite the tests.**
  - `test_laravel_from_lock`: `Dependency("Composer", "laravel/framework", <locked>, <locked>, src)`.
  - `test_symfony_framework_bundle` and `test_symfony_http_kernel_fallback` merge into `test_symfony_packages_listed`: both packages appear as dependencies.
  - `test_unreadable_version_gap`: becomes a dependency with `version=None` and `missing="'<raw>' isn't a version"`. No unrecognised line.
  - New `test_platform_packages_skipped`: `{"require": {"php": "^8.1", "ext-json": "*", "composer-plugin-api": "^2.0", "monolog/monolog": "^3.0"}, "require-dev": {"phpunit/phpunit": "^10.0"}}` gives dependencies `monolog/monolog` and `phpunit/phpunit` only, plus the PHP finding.

- [ ] **Step 2: Run the tests.** Expected: FAIL.

- [ ] **Step 3: Implement.** Delete `PACKAGES`. Use the same version text as npm for `missing`.

- [ ] **Step 4: Run `uv run pytest`.** Expected: all pass.

- [ ] **Step 5: Commit** `feat(composer): list every declared dependency`

---

### Task 6: NuGet package references

**Files:**
- Modify: `src/eolchecker/detectors/dotnet.py`, `tests/detectors/test_dotnet.py`

**Interfaces:**
- Produces: `Dependency("NuGet", id, …)` from project files and `packages.config`. `applies_to` also accepts `packages.config`. The target-framework and `global.json` findings are unchanged.

- [ ] **Step 1: Write failing tests**

  ```python
  def test_package_reference_attribute_and_child(write_files):
      # <ItemGroup><PackageReference Include="Newtonsoft.Json" Version="13.0.3" />
      #            <PackageReference Include="Serilog"><Version>3.1.1</Version></PackageReference></ItemGroup>
      # → Dependency("NuGet", "Newtonsoft.Json", "13.0.3", "13.0.3", src), Dependency("NuGet", "Serilog", "3.1.1", "3.1.1", src)

  def test_central_package_versions(write_files):
      # src/Api/Api.csproj: <PackageReference Include="Serilog" />
      # Directory.Packages.props at repo root: <ItemGroup><PackageVersion Include="Serilog" Version="3.1.1" /></ItemGroup>
      # → Dependency("NuGet", "Serilog", "3.1.1", "3.1.1", Path("src/Api/Api.csproj"))

  def test_versionless_reference_kept_with_reason(write_files):
      # no Directory.Packages.props → Dependency(..., None, "", src, missing="no version in project or Directory.Packages.props")

  def test_version_property_and_range(write_files):
      # Version="$(SerilogVersion)" with <SerilogVersion>3.1.1</SerilogVersion>; Version="[2.0,3.0)" → "2.0"

  def test_packages_config(write_files):
      # <packages><package id="jQuery" version="3.7.1" targetFramework="net48" /></packages>
      # → Dependency("NuGet", "jQuery", "3.7.1", "3.7.1", Path("web/packages.config"))
  ```
  Also extend `test_applies_to` with `packages.config`.

- [ ] **Step 2: Run the tests.** Expected: FAIL.

- [ ] **Step 3: Implement.** Read `PackageReference` items with the existing namespace-agnostic `_local`. Resolve `$(…)` with the merged props. Look up central versions in the nearest `Directory.Packages.props` (via `dirs_up`). `packages.config` takes its own branch in `detect`, with no target-framework logic. Versions go through `lowest()`, and `display` is the raw text.

- [ ] **Step 4: Run `uv run pytest`.** Expected: all pass.

- [ ] **Step 5: Commit** `feat(dotnet): read NuGet package references`

---

### Task 7: Maven detector emits every declared dependency

**Files:**
- Modify: `src/eolchecker/detectors/maven.py`, `tests/detectors/test_maven.py`, `tests/detectors/test_maven_fallback.py`

**Interfaces:**
- Produces: for each `pom.xml`, `Dependency("Maven", "group:artifact", …)` for the `<parent>`, every `<dependencies>` entry, and every `<dependencyManagement>` entry (BOM imports included). Plugins are not included. The Java finding works as today. `INHERITABLE = ("Java",)`.

- [ ] **Step 1: Rewrite the tests.** Java tests (`test_java_*`, `test_aggregator_pom_no_java_gap`, `test_child_property_from_parent`, the encoding and broken-XML tests) stay as they are.
  - `test_spring_boot_parent`: `Dependency("Maven", "org.springframework.boot:spring-boot-starter-parent", "3.1.5", "3.1.5", src)` is in `dependencies`.
  - `test_boot_bom_import_with_property`: `org.springframework.boot:spring-boot-dependencies` with the resolved version.
  - `test_explicit_libs`: each declared lib appears with display = the raw version (e.g. `6.5.2.Final`) and version = `6.5.2`.
  - New `test_plugins_not_listed`: a `maven-compiler-plugin` entry doesn't appear in `dependencies`.
  - Delete `test_tomcat_version_property` (it was framework-specific; no replacement).
  - Delete `test_starter_alone_does_not_report_framework_libs` and `test_spring_framework_bom` (framework-specific).
  - Replace the `test_versionless_declaration_*` and `test_company_parent_gap` tests with `test_versionless_dependency_kept_with_reason`: `<dependency>` without a version gives `Dependency(..., None, "set by parent pom", src, missing="set by parent pom")`, and no unrecognised line from the detector.
  - `test_unresolved_property_gap`: becomes a dependency with `missing="couldn't resolve ${x}"`.
  - `test_maven_fallback.py`:
    - `test_fallback_fills_gaps`: the starter now has version `3.3.2` and `via_maven=True`. Inherited dependencies such as `hibernate-core`, which is in the effective pom but not declared in `COMPANY_POM`, are **not** added. The Java finding is `via_maven`.
    - `test_fallback_failure_keeps_gap` / `test_maven_not_found`: the versionless dependency's `missing` becomes `"set by parent pom (Maven fallback failed)"` or `"… (Maven not found)"`. The Java gap reasons are unchanged.
    - `test_no_gaps_no_run`: a pom with all versions plus Java gives no Maven call.
    - `test_versionless_declaration_without_maven` becomes `missing == "set by parent pom (Maven not found)"`.

- [ ] **Step 2: Run `uv run pytest tests/detectors -v`.** Expected: the rewritten tests FAIL.

- [ ] **Step 3: Implement.** Delete the Spring Boot, Spring Framework, Hibernate and Tomcat blocks and `declared_without_version`.
  - Build dependencies from `_coords` for sections `dependency` and `managed`, plus the parent. Resolve `${…}` in the group, artifact and version.
  - Fallback trigger: `has_gaps` = a Java gap, or any dependency with `version is None`.
  - After the effective pom: build a `group:artifact → raw version` map from its `dependency` and `managed` coords. Fill only the declared dependencies that have no version (`replace(..., version=normalise(raw), display=raw, via_maven=True, missing=None)`).
  - On fallback failure, or with no Maven, append the suffix to `missing` the same way `_with_suffix` does for gaps.

- [ ] **Step 4: Run `uv run pytest`.** Expected: all pass.

- [ ] **Step 5: Commit** `feat(maven): list every declared dependency`

---

### Task 8: Docker detector

**Files:**
- Create: `src/eolchecker/detectors/docker.py`, `tests/detectors/test_docker.py`
- Modify: `src/eolchecker/detectors/__init__.py` (register `DockerDetector()`)

**Interfaces:**
- Produces: `DockerDetector` with `applies_to` / `detect`. It emits `Dependency("Docker", image, version, display, source, tag=tag, missing=…)`. Helper: `split_image(ref: str) -> tuple[str, str | None, str | None]`, returning (name, tag, digest).

- [ ] **Step 1: Write failing tests**

  ```python
  @pytest.mark.parametrize("name, ok", [("Dockerfile", True), ("Dockerfile.prod", True), ("api.Dockerfile", True),
      ("web.dockerfile", True), ("docker-compose.yml", True), ("docker-compose.override.yaml", True),
      ("compose.yaml", True), ("compose.dev.yml", True), ("Dockerfile.md", True), ("README.md", False), ("composer.json", False)])
  def test_applies_to(name, ok): ...

  def test_from_line(write_files):
      # "FROM node:18-alpine3.19\n" → Dependency("Docker", "node", "18", "18-alpine3.19", Path("Dockerfile"), tag="18-alpine3.19")

  def test_multi_stage_platform_and_arg(write_files):
      # "ARG NODE=18\nFROM --platform=$BUILDPLATFORM node:${NODE}-bullseye AS build\nRUN x\nFROM build\nFROM scratch\n"
      # → exactly one dependency: node, version "18", tag "18-bullseye"

  def test_registry_port_is_not_a_tag():
      assert split_image("localhost:5000/app:1.2") == ("localhost:5000/app", "1.2", None)
      assert split_image("localhost:5000/app") == ("localhost:5000/app", None, None)
      assert split_image("node@sha256:abc") == ("node", None, "sha256:abc")

  @pytest.mark.parametrize("line, display, missing", [
      ("FROM node", "latest", "image tag doesn't pin a version"),
      ("FROM node:latest", "latest", "image tag doesn't pin a version"),
      ("FROM node:lts-slim", "lts-slim", "image tag doesn't pin a version"),
      ("FROM node@sha256:abc", "sha256:abc", "image pinned by digest only"),
      ("FROM node:${V}", "${V}", "image tag set by a build variable"),
  ])
  def test_unpinned(write_files, line, display, missing):   # version None, tag kept as written (None when absent)

  def test_digest_with_tag_uses_tag(write_files):            # "FROM node:18@sha256:abc" → version "18"
  def test_os_image_codename_tag(write_files):               # "FROM debian:bookworm-slim" → version None, tag "bookworm-slim", missing "image tag doesn't pin a version"
  def test_line_continuation(write_files):                   # "FROM \\\n  node:18\n" → node 18
  def test_compose_images(write_files):
      # services: {db: {image: "postgres:16"}, web: {image: "${REG:-ghcr.io/acme}/web:${TAG:-1.4}"}, app: {build: "."}}
      # → postgres 16, ghcr.io/acme/web 1.4; app (no image) skipped
  def test_compose_variable_without_default(write_files):    # image: "node:${TAG}" → missing "image tag set by a build variable"
  def test_variable_in_image_name_is_unrecognised(write_files):  # "FROM ${BASE}:1" → Unrecognised(src, "couldn't read the image name in FROM ${BASE}:1")
  def test_broken_compose_unrecognised(write_files):         # ": :" → parse_error
  def test_registered(): assert any(isinstance(d, DockerDetector) for d in DETECTORS)
  ```

- [ ] **Step 2: Run `uv run pytest tests/detectors/test_docker.py -v`.** Expected: FAIL.

- [ ] **Step 3: Implement.**
  - `applies_to`: the name is `Dockerfile` or starts with `Dockerfile.`, or the lower-cased name ends with `.dockerfile`, or it matches `^(docker-)?compose(\..+)?\.ya?ml$`.
  - Version: `re.match(r"[vV]?(\d+(?:\.\d+)*)", tag)` → `normalise`.
  - When the tag is missing, `display` is `latest`. With a digest only, `display` is the digest.
  - Variables: substitute from `ARG` defaults seen so far in the file. Compose uses `${VAR:-d}` / `${VAR-d}` defaults. A leftover `$` in the tag gives `missing="image tag set by a build variable"`. A leftover `$` in the name gives an `Unrecognised` line.

- [ ] **Step 4: Run `uv run pytest`.** Expected: all pass.

- [ ] **Step 5: Commit** `feat: Docker and compose detector`

---

### Task 9: Build the report (table rows, SBOM rows, gaps)

**Files:**
- Modify: `src/eolchecker/rows.py`, `src/eolchecker/models.py`, `tests/test_rows.py`, and the detector modules that call `finding(...)` (only the import names change)

**Interfaces:**
- Consumes: `Catalogue` (T1), `Matcher`, `Match`, `os_from_tag` (T2–3), `Dependency` / `DetectResult` (T2), runtime `Finding`.
- Produces:
  - `models.RUNTIMES = {"Java": "eclipse-temurin", ".NET": "dotnet", ".NET Framework": "dotnetfx", "Node.js": "nodejs", "PHP": "php"}` replaces `COMPONENTS`. `finding()` looks up `RUNTIMES`.
  - `Row(component, version, found_in, end_of_support, latest, status)`, unchanged
  - `SbomRow(ecosystem: str, name: str, version: str, found_in: str, product: str, end_of_support: str, status: str)` (frozen). Blank cells are `""`.
  - `Report(rows: list[Row], sbom: list[SbomRow], unrecognised: list[Unrecognised])`
  - `build_report(result: DetectResult, catalogue: Catalogue) -> Report`

- [ ] **Step 1: Rewrite `tests/test_rows.py` against the fixture catalogue.** Keep the intent of the existing status tests (`_tidy`, major-only cycle, no EOL date, via-Maven suffix), and add:

  ```python
  def test_runtime_rows_bypass_merge():
      # Findings .NET 6 and .NET 8 from one csproj → two rows, Components ".NET", statuses END OF LIFE / supported
  def test_exact_matches_take_lowest():
      # pom deps spring-boot 3.2.0 and spring-boot-starter-web 4.0.1 (both exact) → one "Spring Boot" row, version 3.2.0, END OF LIFE
  def test_versionless_members_do_not_decide():
      # parent spring-boot-starter-parent 3.2.0 (rule) + spring-boot-starter-web None (exact, missing "set by parent pom")
      # → row version "3.2.0"; report.unrecognised == []
  def test_missing_version_one_line_per_product():
      # two versionless Spring Boot deps in one pom → exactly
      # [Unrecognised(Path("pom.xml"), "couldn't read the Spring Boot version (set by parent pom)")]; no Spring Boot row
  def test_rule_matches_use_most_common_version():
      # symfony/http-kernel 6.4.1, symfony/console 6.4.3, symfony/polyfill-mbstring 1.28.0 → row "Symfony", display of a 6.4 member, supported
  def test_untracked_not_in_table_but_in_sbom():
      # npm left-pad 1.3.0 → no row; SbomRow("npm", "left-pad", "1.3.0", "package.json", "", "", "")
  def test_version_not_found():
      # react 15.0.0 → status "version not found", end_of_support "—"
  def test_docker_product_and_os_rows():
      # Dockerfile node 18 tag "18-bullseye" → rows "Debian" 11 (bullseye) END OF LIFE, "Node.js" 18 END OF LIFE
      # SBOM: ("Docker", "node", "18-bullseye", "Dockerfile", "Node.js", "2025-04-30", "END OF LIFE")
      #       and ("Docker", "Debian", "11 (bullseye)", "Dockerfile", "Debian", "2024-08-14", "END OF LIFE")
  def test_os_image_single_row():
      # "debian" version None tag "bookworm-slim" → exactly one row "Debian" "12 (bookworm)" supported; no unrecognised
  def test_unknown_image_still_gets_os_row():
      # "registry.example.com/java-base" tag "17-jammy" → one row "Ubuntu" 22.04 (jammy); the SBOM image row has blank product
  def test_unpinned_alpine_is_unrecognised():
      # node tag "18-alpine" → Node.js row, plus Unrecognised(src, "couldn't read the Alpine Linux version (Alpine version not pinned)")
  def test_sbom_rule_match_outside_chosen_cycle_has_blank_status():
      # symfony/http-kernel 6.4.1, symfony/console 6.4.3, symfony/flex 2.8.0 → flex SBOM row product "Symfony", eos "", status ""
      # http-kernel SBOM row status "supported"
  def test_sbom_exact_rows_use_own_version():
      # hibernate-core 5.6.15 (exact) + org.hibernate:hibernate-validator 6.6.0 (rule) → row Hibernate ORM 5.6.15 END OF LIFE;
      # validator SBOM row status "" (cycle 6.6 != chosen 5.6)
  def test_runtime_sbom_rows():
      # Java 17 from pom.xml → SbomRow("Runtime", "Java", "17", "pom.xml", "Eclipse Temurin", "2027-10-31", "supported")
  def test_sorting():
      # rows by (found_in, component); SBOM rows by (found_in, ecosystem, name)
  def test_detector_unrecognised_passed_through_and_deduped():
  ```

- [ ] **Step 2: Run `uv run pytest tests/test_rows.py -v`.** Expected: FAIL.

- [ ] **Step 3: Implement `build_report`.**
  - Keep `_match`, `_newest_latest` and `_tidy`.
  - Status helper: `_status(version, product) -> tuple[Release | None, end_of_support, status]`.
  - Steps:
    1. Runtime findings: one row and one SBOM row each. Component = `Finding.component`, Product = the catalogue label. A slug missing from the catalogue gives `version not found`.
    2. For each dependency: `match`. If it's Docker with a tag, run `os_from_tag`. If the dependency's own product equals a hit's product and its `version` is None, take over the hit's version/display and drop that hit.
    3. Group members by `(product, source)`. Members are matched dependencies plus OS hits. OS hits count as exact.
    4. Chosen version per spec §5: only versioned members count. If any exact members exist, take the lowest. Otherwise take the most common, ties going to the lowest. Compare versions as int tuples.
    5. A group with no chosen version gives one `Unrecognised(source, f"couldn't read the {label} version ({first missing})")`. `os_from_tag` missing entries give the same shape.
    6. SBOM status for a rule member: only when its matched `Release` is the chosen version's `Release`. Exact members and runtimes use their own version.
  - Untracked rows have blank product/status. Docker OS SBOM rows have Ecosystem `Docker`, Name = OS label.
  - `found_in` gets ` (via Maven)` when the chosen member is `via_maven`.
  - Remove `COMPONENTS` and keep `finding()` working for runtimes. The old `build_rows` and `ReleaseSource` go.
  - Keep the CLI working in this task. Change `main`'s `client` parameter to `catalogue: Callable[[], Catalogue] | None` (default `load_catalogue`), and call `build_report(result, catalogue())` followed by `render(root.name, report.rows, report.unrecognised, console)`. In `tests/test_cli.py`, swap `FakeClient` / `DownClient` for `lambda: fixture_catalogue()` and a loader that raises `ApiUnavailable("timed out")`, with `StubDetector` returning an `@angular/core` 16.2.0 `Dependency`. `--sbom`, the new messages and removing `api.py` come in Task 11.

- [ ] **Step 4: Run `uv run pytest`.** Expected: all pass.

- [ ] **Step 5: Commit** `feat: build table and SBOM rows from catalogue matches`

---

### Task 10: SBOM formats

**Files:**
- Create: `src/eolchecker/sbom.py`, `tests/test_sbom.py`

**Interfaces:**
- Consumes: `SbomRow` (Task 9)
- Produces: `HEADER = ["Ecosystem", "Name", "Version", "Found in", "Product", "End of support", "Status"]`, `to_csv(rows: list[SbomRow]) -> str`, `to_markdown(rows: list[SbomRow]) -> str`, `write_sbom(path: Path, rows: list[SbomRow]) -> None` (raises `ValueError` for a suffix other than `.csv` / `.md`, case-insensitive)

- [ ] **Step 1: Write failing tests**

  ```python
  ROW = SbomRow("npm", "react", "^18.2.0", "web/package.json", "React", "", "no EOL date")
  def test_csv():
      assert to_csv([ROW]) == "Ecosystem,Name,Version,Found in,Product,End of support,Status\nnpm,react,^18.2.0,web/package.json,React,,no EOL date\n"
  def test_csv_quotes_commas(): # name "a,b" → '"a,b"'
  def test_markdown():
      assert to_markdown([ROW]).splitlines() == [
          "| Ecosystem | Name | Version | Found in | Product | End of support | Status |",
          "|---|---|---|---|---|---|---|",
          "| npm | react | ^18.2.0 | web/package.json | React |  | no EOL date |"]
  def test_markdown_escapes_pipes(): # version ">=1 || <2" → ">=1 \|\| <2"
  def test_write_sbom_by_suffix(tmp_path): # .csv and .MD written with matching content
  def test_write_sbom_bad_suffix(tmp_path): # .txt → ValueError
  ```

- [ ] **Step 2: Run the tests.** Expected: FAIL.

- [ ] **Step 3: Implement.** Use `csv.writer(lineterminator="\n")`. Write files as UTF-8.

- [ ] **Step 4: Run `uv run pytest`.** Expected: all pass.

- [ ] **Step 5: Commit** `feat: SBOM as CSV or Markdown`

---

### Task 11: CLI wiring and old API removal

**Files:**
- Modify: `src/eolchecker/cli.py`, `src/eolchecker/report.py`, `tests/test_cli.py`
- Delete: `src/eolchecker/api.py`, `tests/test_api.py`

**Interfaces:**
- Consumes: `load_catalogue`, `ApiUnavailable`, `Catalogue` (T1), `build_report` (T9), `write_sbom` (T10)
- Produces: `main(argv: list[str] | None = None, catalogue: Callable[[], Catalogue] | None = None, detectors=None) -> int`, with `--sbom FILE` and `--no-maven`.

- [ ] **Step 1: Extend `tests/test_cli.py`** (Task 9 already switched it to the fixture catalogue).
  - Keep `test_prints_table` (Angular, 16.2.0, END OF LIFE, 20.3.0), the missing-path and not-a-folder tests (exit 2), `test_api_down_exit_1` (same message), `test_not_recognised_section` and `test_no_maven_flag`.
  - `test_nothing_found_exit_0`: no detectors give `"No dependencies found in {root}"`, and the loader is not called (pass a loader that raises).
  - `test_only_untracked`: a `left-pad` dependency only gives `"No dependencies tracked by endoflife.date found."` in the output, exit 0.
  - `test_sbom_csv(tmp_path)` / `test_sbom_markdown`: the file is written, its first line is the header, and the Angular row is present. The table is still printed.
  - `test_sbom_bad_suffix_exit_2`: `--sbom out.txt` gives exit 2 and `"--sbom file must end in .csv or .md"` on stderr, before scanning.
  - `test_sbom_unwritable_exit_1`: `--sbom` pointing into a missing folder gives exit 1 and `"Couldn't write"` on stderr. The table is still printed.
  - `test_version_not_found_style`: the `version not found` status renders.

- [ ] **Step 2: Run the tests.** Expected: FAIL.

- [ ] **Step 3: Implement.**
  - Check the suffix early.
  - `scan`.
  - If there are no findings, no dependencies and no unrecognised lines, print the "No dependencies found" message, write an empty SBOM (header only) if requested, and return 0.
  - Load the catalogue (`catalogue or load_catalogue`).
  - `build_report`, then `render`. When there are no rows, `render` prints `No dependencies tracked by endoflife.date found.`
  - Write the SBOM and print `SBOM written to {path}`.
  - In `report.py`, swap `STATUS_STYLE` `"unknown"` for `"version not found": "dim"`.
  - Update the argparse description to: `Check whether a repo's dependencies are past end-of-life.`
  - Delete `api.py` and `test_api.py`. Use `grep -rn "eolchecker.api\|from .api" src tests` to confirm nothing still imports them.

- [ ] **Step 4: Run `uv run pytest`.** Expected: all pass.

- [ ] **Step 5: Commit** `feat: --sbom and catalogue-based CLI`

---

### Task 12: Guard test against the live catalogue, and README

**Files:**
- Modify: `tests/test_end_to_end.py`, `README.md`, `pyproject.toml` (description)

- [ ] **Step 1: Rewrite the end-to-end test.** It writes a repo with these files:
  - `backend/pom.xml`: parent `spring-boot-starter-parent` 3.1.5, `java.version` 17, dependencies `org.springframework:spring-core` 6.0.0 and `org.hibernate.orm:hibernate-core` 6.2.0.Final
  - `frontend/package.json`: `@angular/core` 16.2.0, `angular` 1.8.2, `react` 18.2.0, `next` 13.5.0
  - `web/composer.json`: `php` >=7.4, `laravel/framework` ^10.0, `symfony/http-kernel` ^6.4
  - `api/Api.csproj`: net8.0
  - `Dockerfile`: `FROM node:18-bullseye`

  It runs `main([str(root), "--no-maven", "--sbom", str(root / "sbom.md")])` against the real catalogue, with `load_catalogue(tmp_path / "cache.json")` passed as the loader so the user's cache isn't touched. Assertions:
  - The output contains `Spring Boot`, `Spring Framework`, `Hibernate ORM`, `Angular`, `AngularJS`, `React`, `Next.js`, `Laravel`, `Symfony`, `Node.js`, `Debian`, `Java`, `.NET`, `PHP`.
  - `"END OF LIFE"` appears in the output and `"version not found"` doesn't.
  - The sbom.md file contains `| Maven | org.springframework.boot:spring-boot-starter-parent | 3.1.5 |`.

- [ ] **Step 2: Run `EOLCHECKER_NETWORK=1 uv run pytest tests/test_end_to_end.py -v`.** Expected: PASS. If a framework is missing, the catalogue changed: report it, don't hard-code a workaround.

- [ ] **Step 3: Update the README.**
  - "What it checks" now says: any product endoflife.date tracks, matched from its package and image names plus the rules in spec §3; runtime rules for Java/Node.js/PHP/.NET; the files read (add NuGet `PackageReference`, `Directory.Packages.props`, `packages.config`, Dockerfiles, compose files); OS rows from image tags.
  - Add `--sbom out.csv|out.md` to "Use".
  - Note the catalogue cache location and the 24-hour refresh.
  - Add a "Known gaps" list copied from the spec.
  - Remove the sentence about Spring Framework/Hibernate/Tomcat only being reported when declared.
  - Change the `pyproject.toml` description to `Check whether a repo's dependencies are past end-of-life`.

- [ ] **Step 4: Run `uv run pytest`.** Expected: all pass.

- [ ] **Step 5: Commit** `docs: README for catalogue matching, Docker and SBOM; live guard test`
