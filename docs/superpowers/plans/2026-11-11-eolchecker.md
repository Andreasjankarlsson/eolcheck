# eolchecker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Python CLI, `eolchecker <folder>`, that finds the major frameworks/runtimes in a locally cloned repo and prints their version, end-of-support date, newest release and status, using the endoflife.date v1 API.

**Architecture:** A scanner walks the folder and hands each file to small, self-contained detectors (npm, composer, .NET, Maven). Detectors return `Finding`s and `Unrecognised` gaps. A client fetches each endoflife.date product once, a matcher turns findings into table rows, and a `rich` table prints them. Adding a framework means adding to one detector.

**Tech Stack:** Python 3.11+, `uv`, `httpx`, `rich`, `pyyaml` (pnpm lock files), `pytest`. Standard-library `xml.etree.ElementTree`, `json`, `tomllib`, `argparse`, `subprocess`.

**Spec:** `docs/superpowers/specs/2026-11-11-eolchecker-design.md` (read it alongside this plan).

## Global Constraints

- Python 3.11+ (`requires-python = ">=3.11"`); the machine's `python3` is 3.7, so always run through `uv` (`uv run ...`).
- Data from the endoflife.date v1 API only: base URL `https://endoflife.date/api/v1`, `GET /products/{slug}`, follow redirects. No hard-coded EOL dates.
- One request per product found per run; no caching.
- Skip directories: `.git`, `node_modules`, `vendor`, `target`, `build`, `dist`, `bin`, `obj`, `.idea`, `.venv`.
- Status values exactly: `END OF LIFE`, `supported`, `no EOL date`, `unknown`.
- Table columns exactly: `Component`, `Version`, `Found in`, `End of support`, `Latest`, `Status`. Null `eolFrom` shows `—`.
- "Not recognised" lists only files where one of the 15 components is clearly in use but no version could be determined; files using none of them are skipped silently.
- Exit codes: path missing → 2; endoflife.date unreachable → 1; otherwise 0 (including "No supported frameworks found in <path>").
- `netstandard*` targets are ignored. Gradle build files, Dockerfiles and CI configs are not read.
- Do not modify `.idea/` or `eolchecker.iml`.
- The 15 components and their slugs:

| Component | Slug |
|---|---|
| Spring Boot | `spring-boot` |
| Spring Framework | `spring-framework` |
| Java | `eclipse-temurin` |
| Hibernate ORM | `hibernate-orm` |
| Apache Tomcat | `tomcat` |
| .NET | `dotnet` |
| .NET Framework | `dotnetfx` |
| Angular | `angular` |
| AngularJS | `angularjs` |
| React | `react` |
| Next.js | `nextjs` |
| Node.js | `nodejs` |
| PHP | `php` |
| Laravel | `laravel` |
| Symfony | `symfony` |

## Review Focus

1. **Malformed or unusual files** (broken XML/JSON, a UTF-8 BOM, a namespaced old-style `.csproj`): the scan must keep going and list the file under "Not recognised" with `couldn't parse <file>`, never crash. Tests in Tasks 4, 6 and 7.
2. **Symlinked directories, including loops**: never follow them, so a scan always ends. Test in Task 3.
3. **Lock file at the workspace root, not next to `package.json`** (npm/yarn/pnpm workspaces): walk up to the repo root to find it. Test in Task 4.
4. **Version strings with suffixes** (`6.4.1.Final`, `3.2.0-RC1`, `v6.4.1`, `net8.0-windows`, `1.8`): normalise them before matching. Tests in Tasks 1, 6 and 7.
5. **One product 404s, or the network fails partway through**: a 404 makes only that product's rows `unknown`; a network error, 429 or 5xx aborts with exit 1 and a clear message. Tests in Task 2.

---

## File Structure

```
pyproject.toml                       # package, deps, console script
.gitignore                           # .venv, __pycache__, .pytest_cache, *.egg-info
README.md                            # install + usage
src/eolchecker/
  __init__.py
  models.py                          # Finding, Unrecognised, DetectResult, COMPONENTS
  versions.py                        # version normalising and range handling
  api.py                             # endoflife.date client, Release, errors
  rows.py                            # matching findings to releases → Row
  scan.py                            # folder walk + running detectors
  report.py                          # rich table output
  cli.py                             # argparse entry point
  detectors/
    __init__.py                      # Detector protocol + DETECTORS registry
    npm.py                           # package.json, lock files, .nvmrc, .node-version
    composer.py                      # composer.json / composer.lock
    dotnet.py                        # *.csproj/*.fsproj/*.vbproj, Directory.Build.props, global.json
    maven.py                         # pom.xml parsing, properties, in-repo parents
    maven_fallback.py                # mvn help:effective-pom runner
tests/
  conftest.py                        # write_files helper fixture
  test_versions.py  test_api.py  test_rows.py  test_scan.py  test_cli.py
  detectors/test_npm.py  test_composer.py  test_dotnet.py  test_maven.py
  detectors/test_maven_fallback.py
```

Tests build their sample repos inside `tmp_path` with the `write_files` fixture. There are no checked-in fixture folders.

---

### Task 1: Project skeleton, models and version helpers

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `src/eolchecker/__init__.py`, `src/eolchecker/models.py`, `src/eolchecker/versions.py`, `tests/conftest.py`
- Test: `tests/test_versions.py`

**Interfaces:**
- Produces:
  ```python
  # models.py
  COMPONENTS: dict[str, str]   # component name → slug, in the table order above (also the row sort order)

  @dataclass(frozen=True)
  class Finding:
      component: str          # e.g. "Spring Boot"
      product: str            # slug, e.g. "spring-boot"
      version: str            # normalised, for matching: "3.1.5", "17", "8.0", "4.7.2"
      display: str            # Version column text: "3.1.5", ">=7.4", "net8.0", "SDK 8.0.100"
      source: Path            # relative to scan root
      via_maven: bool = False

  @dataclass(frozen=True)
  class Unrecognised:
      source: Path            # relative to scan root
      reason: str             # e.g. "couldn't read the Spring Boot version"

  @dataclass
  class DetectResult:
      findings: list[Finding] = field(default_factory=list)
      unrecognised: list[Unrecognised] = field(default_factory=list)
      def extend(self, other: "DetectResult") -> None

  def finding(component: str, version: str, display: str, source: Path, via_maven: bool = False) -> Finding
      # looks up product from COMPONENTS

  # versions.py
  def normalise(raw: str) -> str | None      # strip "v", qualifiers; "1.8"→"8" is NOT done here (Java-specific, see Task 7)
  def is_range(raw: str) -> bool
  def lowest(raw: str) -> str | None         # lowest version a range allows; None for "*", "latest", "", urls, "workspace:*"
  def cycle_candidates(version: str) -> list[str]   # ["4.7.2", "4.7", "4"] (deduped, full first)
  ```
- `tests/conftest.py` fixture: `write_files(tmp_path)` returns a function `write(files: dict[str, str]) -> Path` that writes each relative path with its content and returns `tmp_path`.

- [ ] **Step 1: Set up the project**

Check `uv --version` (install with `brew install uv` if missing). `pyproject.toml`: name `eolchecker`, version `0.1.0`, `requires-python = ">=3.11"`, dependencies `httpx`, `rich`, `pyyaml`, dev dependency group with `pytest`, `[project.scripts] eolchecker = "eolchecker.cli:main"`, src layout with the hatchling build backend. `.gitignore`: `.venv/`, `__pycache__/`, `.pytest_cache/`, `*.egg-info/`. Run `uv sync`. Expected: it creates `.venv` with Python ≥3.11.

- [ ] **Step 2: Write failing tests in `tests/test_versions.py`**

```python
import pytest
from eolchecker.versions import normalise, is_range, lowest, cycle_candidates

@pytest.mark.parametrize("raw,expected", [
    ("3.1.5", "3.1.5"), ("v6.4.1", "6.4.1"), ("6.4.1.Final", "6.4.1"),
    ("3.2.0-RC1", "3.2.0"), ("18", "18"), ("v18.17.0", "18.17.0"),
    ("latest", None), ("", None),
])
def test_normalise(raw, expected):
    assert normalise(raw) == expected

@pytest.mark.parametrize("raw,expected", [
    ("^16.2.0", True), ("~3.1", True), (">=7.4", True), ("16.x", True),
    ("^7.4|^8.0", True), ("^7.4 || ^8.0", True), ("16.2.0", False), ("8.2", False),
])
def test_is_range(raw, expected):
    assert is_range(raw) is expected

@pytest.mark.parametrize("raw,expected", [
    ("^16.2.0", "16.2.0"), ("~3.1", "3.1"), (">=7.4", "7.4"), ("16.x", "16"),
    ("^8.0|^7.4", "7.4"), ("^8.0 || ^7.4", "7.4"), (">=18 <21", "18"),
    ("16.2.0", "16.2.0"), ("*", None), ("latest", None),
    ("workspace:*", None), ("git+https://github.com/x/y.git", None),
])
def test_lowest(raw, expected):
    assert lowest(raw) == expected

def test_cycle_candidates():
    assert cycle_candidates("4.7.2") == ["4.7.2", "4.7", "4"]
    assert cycle_candidates("17") == ["17"]
    assert cycle_candidates("8.0") == ["8.0", "8"]
```

- [ ] **Step 3: Run to verify they fail**

Run: `uv run pytest tests/test_versions.py -v`
Expected: FAIL (ImportError).

- [ ] **Step 4: Implement `models.py` and `versions.py` per the Interfaces**

For `lowest`, split alternatives on `||` or `|`, and within each one take the first numeric version token (dropping `^ ~ >= > = v` and `.x`/`.*` wildcards). Compare alternatives as integer tuples and return the smallest, in its original dotted form.

- [ ] **Step 5: Run to verify they pass**

Run: `uv run pytest tests/test_versions.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock .gitignore src tests
git commit -m "feat: project skeleton, models and version helpers"
```

---

### Task 2: endoflife.date client and row building

**Files:**
- Create: `src/eolchecker/api.py`, `src/eolchecker/rows.py`
- Test: `tests/test_api.py`, `tests/test_rows.py`

**Interfaces:**
- Consumes: `Finding`, `cycle_candidates` (Task 1).
- Produces:
  ```python
  # api.py
  BASE_URL = "https://endoflife.date/api/v1"
  @dataclass(frozen=True)
  class Release:
      name: str; release_date: str; is_eol: bool; eol_from: str | None; latest: str | None
  class ApiUnavailable(Exception): ...          # message is human readable
  class EolClient:
      def __init__(self, http: httpx.Client | None = None)   # default: follow_redirects=True, timeout=15, User-Agent "eolchecker/0.1"
      def releases(self, product: str) -> list[Release] | None   # None on 404; raises ApiUnavailable on network error/429/5xx/bad JSON

  # rows.py
  @dataclass(frozen=True)
  class Row:
      component: str; version: str; found_in: str; end_of_support: str; latest: str; status: str
  def build_rows(findings: list[Finding], client: EolClient) -> list[Row]
  ```
  - Fetch each distinct product once.
  - Match a release by `cycle_candidates(f.version)` against `Release.name`, first hit wins.
  - `Row.version` = `f.display`. `Row.found_in` = `str(f.source)`, plus `" (via Maven)"` when `via_maven` is set.
  - `end_of_support` = `eol_from` or `"—"`.
  - `latest` = `latest` of the release with the greatest `release_date`, or `"—"`.
  - Status: no match or product 404 → `unknown` (end of support `—`); `is_eol` → `END OF LIFE`; `eol_from is None` → `no EOL date`; else `supported`.
  - Sort rows by `found_in`, then by the `COMPONENTS` order.

- [ ] **Step 1: Write failing tests**

`tests/test_api.py`: build an `httpx.Client(transport=httpx.MockTransport(handler))`.
- `test_releases_parses_v1_payload`: the handler returns `{"result": {"releases": [{"name": "3.1", "releaseDate": "2023-05-18", "isEol": True, "eolFrom": "2024-06-30", "latest": {"name": "3.1.12"}}]}}` for `/api/v1/products/spring-boot`. Assert `client.releases("spring-boot") == [Release("3.1", "2023-05-18", True, "2024-06-30", "3.1.12")]`.
- `test_404_returns_none`: assert the result `is None`.
- `test_429_raises` and `test_500_raises`: `pytest.raises(ApiUnavailable)`.
- `test_connect_error_raises`: the handler raises `httpx.ConnectError("boom")` → `ApiUnavailable`.
- `test_follows_redirect`: a 301 with `Location: /api/v1/products/new-name` then 200 → releases parsed.

`tests/test_rows.py`: a `FakeClient` with a `releases(product)` method backed by a dict, counting calls.
- `test_eol_row`: Spring Boot `3.1.5` from `backend/pom.xml` → `Row("Spring Boot", "3.1.5", "backend/pom.xml", "2024-06-30", "4.1.0", "END OF LIFE")`. Data: releases 3.1 (EOL) and 4.1 (`releaseDate` 2026-05-20, latest 4.1.0).
- `test_major_only_cycle`: .NET version `8.0` matches release `8` (`isEol` False, `eolFrom` 2026-11-10) → status `supported`.
- `test_no_eol_date`: React `17.0.2` matches `17` with `eolFrom` None → status `no EOL date`, end of support `—`.
- `test_unknown_cycle` and `test_product_404`: status `unknown`.
- `test_one_fetch_per_product`: two Angular findings → `FakeClient` called once for `angular`.
- `test_via_maven_suffix`: `found_in == "api/pom.xml (via Maven)"`.
- `test_sorted_by_file_then_component`.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_api.py tests/test_rows.py -v` → FAIL (ImportError).

- [ ] **Step 3: Implement `api.py` and `rows.py` per the Interfaces**

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/test_api.py tests/test_rows.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/eolchecker/api.py src/eolchecker/rows.py tests/test_api.py tests/test_rows.py
git commit -m "feat: endoflife.date client and row matching"
```

---

### Task 3: Scanner, report and CLI

**Files:**
- Create: `src/eolchecker/detectors/__init__.py`, `src/eolchecker/scan.py`, `src/eolchecker/report.py`, `src/eolchecker/cli.py`, `README.md`
- Test: `tests/test_scan.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `DetectResult`, `Finding`, `Unrecognised` (Task 1); `EolClient`, `ApiUnavailable`, `build_rows`, `Row` (Task 2).
- Produces:
  ```python
  # detectors/__init__.py
  @dataclass(frozen=True)
  class Context:
      root: Path
      use_maven: bool = True
  class Detector(Protocol):
      def applies_to(self, path: Path) -> bool
      def detect(self, path: Path, ctx: Context) -> DetectResult
  DETECTORS: list[Detector] = []      # Tasks 4–8 each append their detector here

  # scan.py
  SKIP_DIRS = frozenset({".git", "node_modules", "vendor", "target", "build", "dist", "bin", "obj", ".idea", ".venv"})
  def iter_files(root: Path) -> Iterator[Path]          # sorted, skips SKIP_DIRS, never follows symlinked dirs
  def scan(root: Path, ctx: Context, detectors: Sequence[Detector] | None = None) -> DetectResult
      # detectors=None → DETECTORS. Any exception from a detector on a file
      # becomes Unrecognised(rel, f"couldn't parse {name}") so the scan continues.

  # report.py
  def render(repo_name: str, rows: list[Row], unrecognised: list[Unrecognised], console: Console) -> None

  # cli.py
  def main(argv: list[str] | None = None, client: EolClient | None = None, detectors=None) -> int
  ```
  - CLI arguments: positional `path`, plus `--no-maven` (sets `Context.use_maven=False`).
  - Error messages go to stderr: `Path not found: <path>` (exit 2) and `Couldn't fetch end-of-life dates from endoflife.date: <reason>` (exit 1).
  - When nothing is found and nothing is unrecognised, print `No supported frameworks found in <path>` and exit 0.
  - Report layout: the repo folder name as a heading, then the table, then `Not recognised:` with one line per item, `  <source>: <reason>`.
  - Status colours: `END OF LIFE` bold red, `supported` green, `no EOL date` yellow, `unknown` dim.

- [ ] **Step 1: Write failing tests**

`tests/test_scan.py`:
- `test_skips_ignored_dirs`: files in `node_modules/x/package.json`, `vendor/a/composer.json` and `app/package.json` → `iter_files` yields only `app/package.json`.
- `test_does_not_follow_symlink_loop`: `os.symlink(tmp_path, tmp_path / "loop")` → `iter_files` finishes and yields no paths under `loop/`.
- `test_detector_exception_becomes_unrecognised`: a fake detector that raises on `bad.json` → `scan(...).unrecognised == [Unrecognised(Path("bad.json"), "couldn't parse bad.json")]`.
- `test_scan_collects_findings_with_relative_paths`.

`tests/test_cli.py` (use `capsys`, a `FakeClient`, and a fake detector that returns one Angular `16.2.0` finding from `frontend/package.json`):
- `test_prints_table`: the output contains `Angular`, `16.2.0`, `frontend/package.json`, `END OF LIFE`, `Latest`.
- `test_missing_path_exit_2`: `main(["/nope"]) == 2`, and stderr contains `Path not found: /nope`.
- `test_api_down_exit_1`: the client raises `ApiUnavailable("timed out")` → 1, and stderr contains `Couldn't fetch end-of-life dates from endoflife.date: timed out`.
- `test_nothing_found_exit_0`: with no detectors → 0, and the output contains `No supported frameworks found in`.
- `test_not_recognised_section`: a detector that returns `Unrecognised(Path("tools/pom.xml"), "couldn't read the Spring Boot version")` → the output contains `Not recognised:` and that line.
- `test_no_maven_flag`: the fake detector records `ctx.use_maven`; `main([str(tmp_path), "--no-maven"], ...)` → it recorded `False`.

Render with `Console(width=200)` in `main` when stdout isn't a terminal, so tests don't wrap columns.

- [ ] **Step 2: Run to verify they fail** — `uv run pytest tests/test_scan.py tests/test_cli.py -v` → FAIL.

- [ ] **Step 3: Implement per the Interfaces.** `iter_files` uses `os.walk(root, followlinks=False)`, prunes `SKIP_DIRS` in place, and sorts dirnames and filenames.

- [ ] **Step 4: Run to verify they pass** — `uv run pytest -v` → all PASS.

- [ ] **Step 5: Write `README.md`**: install with `uv tool install .`, run with `eolchecker ~/code/some-repo [--no-maven]`, the list of 15 components, and a note that it needs internet access.

- [ ] **Step 6: Commit**

```bash
git add src tests README.md
git commit -m "feat: scanner, report and CLI"
```

---

### Task 4: npm detector (Angular, AngularJS, React, Next.js, Node.js)

**Files:**
- Create: `src/eolchecker/detectors/npm.py`
- Modify: `src/eolchecker/detectors/__init__.py` (register `NpmDetector()`)
- Test: `tests/detectors/test_npm.py`

**Interfaces:**
- Consumes: `Context`, `DetectResult`, `finding`, `Unrecognised`, `lowest`, `is_range`, `normalise`.
- Produces: `class NpmDetector` with `applies_to` true for `package.json`, `.nvmrc`, `.node-version`.
  - Packages: `@angular/core`→Angular, `angular`→AngularJS, `react`→React, `next`→Next.js, looked up in `dependencies`, `devDependencies` and `peerDependencies`.
  - `engines.node`→Node.js.
  - Lock lookup: walk from the `package.json` dir up to `ctx.root`, using the first dir with `package-lock.json`, `yarn.lock` or `pnpm-lock.yaml`. Read the installed version for that package:
    - `package-lock.json`: v2/v3 `packages["node_modules/<name>"].version`, or v1 `dependencies[<name>].version`.
    - `yarn.lock`: the entry whose header contains `<name>@<declared>` (classic `version "x"` or berry `version: x`).
    - `pnpm-lock.yaml`: `importers[<relative dir or ".">].dependencies|devDependencies[<name>]`, either a string or `{version: ...}`, with the version cut at `(`.
  - With a locked version: `version` and `display` = the locked version. Without one: `version = lowest(declared)`, and `display = declared` when `is_range(declared)`, else the normalised version.
  - Undeterminable (`lowest` None, no lock entry) → `Unrecognised(source, f"couldn't read the {component} version")`.
  - `.nvmrc`/`.node-version`: the first line, `normalise`d. Non-numeric values (`lts/hydrogen`, `node`) → `Unrecognised(source, "couldn't read the Node.js version")`.

- [ ] **Step 1: Write failing tests** (each one uses `write_files`):
- `test_angular_from_package_json_without_lock`: `{"dependencies": {"@angular/core": "^16.2.0"}}` → `Finding("Angular", "angular", "16.2.0", "^16.2.0", Path("frontend/package.json"))`.
- `test_lockfile_wins`: same, plus `package-lock.json` v3 with `packages["node_modules/@angular/core"].version = "16.2.12"` → version and display `16.2.12`.
- `test_lock_at_workspace_root`: `package-lock.json` at the root, `apps/web/package.json` with `react ^18.2.0`, root lock has `node_modules/react` `18.3.1` → `18.3.1`.
- `test_yarn_classic_lock` and `test_pnpm_lock`: pick the right version from each format.
- `test_angularjs_react_next_and_engines`: one `package.json` with all four → four findings, Node `display == ">=18"`, `version == "18"`.
- `test_latest_tag_is_unrecognised`: `"next": "latest"` → `Unrecognised(Path("package.json"), "couldn't read the Next.js version")`.
- `test_package_json_without_frameworks_is_silent`: `{"dependencies": {"lodash": "^4"}}` → empty result.
- `test_nvmrc`: `v18.17.0` → Node.js `18.17.0`. `test_nvmrc_lts_alias_unrecognised`.
- `test_bom_and_broken_json`: a `package.json` with a UTF-8 BOM parses (read with `utf-8-sig`); a broken `package.json` → `Unrecognised(..., "couldn't parse package.json")`.

- [ ] **Step 2: Run to verify they fail** — `uv run pytest tests/detectors/test_npm.py -v` → FAIL.
- [ ] **Step 3: Implement `NpmDetector` and register it.**
- [ ] **Step 4: Run to verify they pass** — `uv run pytest -v` → all PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat: npm detector for Angular, React, Next.js and Node"`

---

### Task 5: Composer detector (PHP, Laravel, Symfony)

**Files:**
- Create: `src/eolchecker/detectors/composer.py`
- Modify: `src/eolchecker/detectors/__init__.py` (register)
- Test: `tests/detectors/test_composer.py`

**Interfaces:**
- Produces: `class ComposerDetector`, which applies to `composer.json`.
  - PHP: `config.platform.php` is used if present, and is exact. Otherwise `require.php`, which is a range, so display is as written.
  - Laravel: `laravel/framework`. Symfony: `symfony/framework-bundle`, falling back to `symfony/http-kernel`.
  - For Laravel and Symfony, a `composer.lock` in the same dir wins: `packages[]` (then `packages-dev[]`), matched by `name`, with `version` normalised to strip `v`.
  - Gaps follow the same `couldn't read the {component} version` rule as Task 4.

- [ ] **Step 1: Write failing tests**
- `test_php_range`: `{"require": {"php": ">=7.4"}}` → `Finding("PHP", "php", "7.4", ">=7.4", Path("composer.json"))`.
- `test_platform_php_wins`: `config.platform.php = "8.2.10"` → version and display `8.2.10`.
- `test_laravel_from_lock`: require `^10.0`, lock `v10.48.2` → `10.48.2`.
- `test_symfony_http_kernel_fallback`: `symfony/http-kernel ^6.4` → Symfony `6.4`, display `^6.4`.
- `test_no_frameworks_silent`, and `test_broken_json_unrecognised`.

- [ ] **Step 2: Run to verify they fail** — `uv run pytest tests/detectors/test_composer.py -v` → FAIL.
- [ ] **Step 3: Implement and register.**
- [ ] **Step 4: Run to verify they pass** — `uv run pytest -v` → PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat: composer detector for PHP, Laravel and Symfony"`

---

### Task 6: .NET detector

**Files:**
- Create: `src/eolchecker/detectors/dotnet.py`
- Modify: `src/eolchecker/detectors/__init__.py` (register)
- Test: `tests/detectors/test_dotnet.py`

**Interfaces:**
- Produces: `class DotnetDetector`, which applies to `*.csproj`, `*.fsproj`, `*.vbproj` and `global.json`. `Directory.Build.props` is only read as a helper and never reported on its own.
  - `def parse_tfm(tfm: str) -> tuple[str, str] | None` returns `(component, version)`:

| TFM | Result |
|---|---|
| `net8.0`, `net8.0-windows` | `(".NET", "8.0")` (major ≥ 5) |
| `netcoreapp3.1` | `(".NET", "3.1")` |
| `net48` | `(".NET Framework", "4.8")` |
| `net472` | `(".NET Framework", "4.7.2")` |
| `v4.7.2` (TargetFrameworkVersion) | `(".NET Framework", "4.7.2")` |
| `netstandard2.0` | `None` (ignored) |

  - Project files: read `TargetFramework`, `TargetFrameworks` (split on `;`) and `TargetFrameworkVersion`, ignoring XML namespaces (old-style projects use the msbuild namespace). One finding per target, with display = the TFM as written and source = the project file.
  - If the project has none of these, use the nearest `Directory.Build.props` from the project's dir up to `ctx.root`.
  - Resolve `$(Name)` from `<PropertyGroup>` in the project, then in the props chain.
  - Still nothing, or unresolved → `Unrecognised(source, "couldn't read the .NET target framework")`. A project whose targets are all `netstandard` → nothing.
  - `global.json`: `sdk.version` `8.0.100` → `Finding(".NET", "dotnet", "8.0.100", "SDK 8.0.100", ...)`.

- [ ] **Step 1: Write failing tests**
- `test_parse_tfm` parametrised over the table above.
- `test_sdk_style_csproj`: `<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net8.0</TargetFramework></PropertyGroup></Project>` in `api/Api.csproj` → `Finding(".NET", "dotnet", "8.0", "net8.0", Path("api/Api.csproj"))`.
- `test_multi_target`: `net8.0;net48;netstandard2.0` → two findings, one .NET and one .NET Framework.
- `test_old_style_namespaced`: `<Project xmlns="http://schemas.microsoft.com/developer/msbuild/2003">…<TargetFrameworkVersion>v4.7.2</TargetFrameworkVersion>` → .NET Framework `4.7.2`.
- `test_directory_build_props`: the root `Directory.Build.props` sets `net6.0`, and `src/A/A.csproj` has no target → finding with source `src/A/A.csproj`.
- `test_property_reference`: `<TargetFramework>$(AppTfm)</TargetFramework>`, with `AppTfm` defined in props → resolved.
- `test_no_target_unrecognised`, `test_netstandard_only_silent`, `test_global_json`, and `test_broken_xml_unrecognised` (`couldn't parse Api.csproj`).

- [ ] **Step 2: Run to verify they fail** — `uv run pytest tests/detectors/test_dotnet.py -v` → FAIL.
- [ ] **Step 3: Implement and register.**
- [ ] **Step 4: Run to verify they pass** — `uv run pytest -v` → PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat: .NET detector"`

---

### Task 7: Maven detector (direct read)

**Files:**
- Create: `src/eolchecker/detectors/maven.py`
- Modify: `src/eolchecker/detectors/__init__.py` (register)
- Test: `tests/detectors/test_maven.py`

**Interfaces:**
- Produces:
  ```python
  def java_version(raw: str) -> str | None        # "1.8"→"8", "17"→"17", "21.0.1"→"21"
  @dataclass
  class PomReading:
      result: DetectResult                         # findings + gaps
      has_gaps: bool                               # True if anything went to unrecognised
  def read_pom(pom_xml: str, source: Path, parent_props: dict[str, str], *, check_java: bool) -> PomReading
      # pure function; also used by Task 8 on effective-pom output
  class MavenDetector:                             # applies to pom.xml
      def detect(self, path: Path, ctx: Context) -> DetectResult
  ```
  Rules for `read_pom`, ignoring XML namespaces:
  - **Spring Boot**, from the first that applies:
    - a `parent` of `org.springframework.boot:spring-boot-starter-parent`
    - a `dependencyManagement` import of `org.springframework.boot:spring-boot-dependencies`
    - an explicit version on any `org.springframework.boot:*` dependency or plugin

    If Boot artifacts are used but no version is found → gap `couldn't read the Spring Boot version`.
  - **Spring Framework**: an explicit version on `org.springframework:spring-*` dependencies, or an import of `org.springframework:spring-framework-bom`. No version → no row (Boot covers it).
  - **Hibernate ORM**: `org.hibernate:hibernate-core` or `org.hibernate.orm:hibernate-core` with an explicit version.
  - **Apache Tomcat**: `org.apache.tomcat.embed:tomcat-embed-core` with an explicit version, or a `tomcat.version` property.
  - **Java**: the first of the properties `maven.compiler.release`, `maven.compiler.source`, `java.version`, then the `maven-compiler-plugin` `<configuration>` `release`/`source`. Pass it through `java_version`. When `check_java` is set and the pom isn't `<packaging>pom</packaging>`, a missing Java version → gap `couldn't read the Java version`.
  - **Properties**: `${x}` resolves from the pom's own `<properties>`, then `parent_props`, plus `project.version` and `project.parent.version`. An unresolvable reference on a needed value → gap `couldn't resolve ${x}`.
  - **In-repo parent**: `MavenDetector.detect` loads the parent pom (`relativePath`, default `../pom.xml`, only if it exists inside `ctx.root` and its `artifactId` matches). It merges that pom's properties into `parent_props` recursively, and inherits its Java version when the child has none.

- [ ] **Step 1: Write failing tests**
- `test_java_version` parametrised over `1.8`, `17`, `21.0.1`.
- `test_spring_boot_parent`: starter parent `3.1.5`, `<java.version>17</java.version>` → `Spring Boot 3.1.5` and `Java 17`, both from `backend/pom.xml`.
- `test_boot_bom_import_with_property`: `<spring-boot.version>3.2.4</spring-boot.version>`, imported as `${spring-boot.version}` → `3.2.4`.
- `test_explicit_libs`: `hibernate-core 6.4.1.Final` → Hibernate `6.4.1` (display `6.4.1.Final`); `tomcat-embed-core 10.1.19`; `spring-core 6.1.5` → three findings.
- `test_boot_managed_framework_not_reported`: Boot parent + `spring-core` without a version → no Spring Framework row.
- `test_child_inherits_from_in_repo_parent`: root pom with `<java.version>21</java.version>` and Boot parent; `app/pom.xml` with a parent pointing at the root and no Java → `app/pom.xml` gets `Java 21`, with no gap.
- `test_company_parent_gap`: parent `com.acme:acme-parent:5` (not in repo), `spring-boot-starter-web` with no version, no Java → gaps `couldn't read the Spring Boot version` and `couldn't read the Java version`, and `has_gaps` is True.
- `test_aggregator_pom_no_java_gap`: `<packaging>pom</packaging>` and no Java → no gap.
- `test_broken_xml_unrecognised`.

- [ ] **Step 2: Run to verify they fail** — `uv run pytest tests/detectors/test_maven.py -v` → FAIL.
- [ ] **Step 3: Implement and register.**
- [ ] **Step 4: Run to verify they pass** — `uv run pytest -v` → PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat: Maven detector"`

---

### Task 8: Maven effective-pom fallback

**Files:**
- Create: `src/eolchecker/detectors/maven_fallback.py`
- Modify: `src/eolchecker/detectors/maven.py` (call the fallback when there are gaps)
- Test: `tests/detectors/test_maven_fallback.py`

**Interfaces:**
- Consumes: `read_pom`, `PomReading`, `MavenDetector` (Task 7), `Context.use_maven`.
- Produces:
  ```python
  def find_maven(pom: Path, root: Path) -> list[str] | None
      # nearest executable mvnw from pom dir up to root → [str(mvnw)], else shutil.which("mvn") → ["mvn"], else None
  Runner = Callable[[list[str], Path], subprocess.CompletedProcess]
  def effective_pom(pom: Path, root: Path, runner: Runner = run_subprocess) -> str | None
      # runs <maven> -q -B -N -f <pom> help:effective-pom -Doutput=<tmpfile>, timeout 180s, cwd = pom dir;
      # returns file contents, or None on missing maven / non-zero exit / timeout
  ```
  `MavenDetector` takes an optional `runner` in `__init__`, for tests. When `read_pom` reports `has_gaps` and `ctx.use_maven` is set, the detector calls `effective_pom`:
  - **Success:** it re-reads the output with `read_pom(..., check_java=True)`. Findings that fill a gap get `via_maven=True`, and those gaps are removed. Findings already read directly stay as they are.
  - **Failure:** each remaining gap's reason gets `" (Maven fallback failed)"`, or `" (Maven not found)"` if `find_maven` returned None, appended.

- [ ] **Step 1: Write failing tests** (with a fake runner that writes canned effective-pom XML to the `-Doutput=` path):
- `test_fallback_fills_gaps`: the company-parent pom from Task 7, plus an effective pom containing `spring-boot-starter-web` `3.3.2` and `maven.compiler.release` `17` → findings Spring Boot `3.3.2` and Java `17` with `via_maven=True`, and no unrecognised.
- `test_no_maven_flag_skips`: `Context(use_maven=False)` → the runner is never called and the gaps remain.
- `test_fallback_failure_keeps_gap`: the runner returns code 1 → reason `couldn't read the Spring Boot version (Maven fallback failed)`.
- `test_maven_not_found`: no `mvnw`, and `shutil.which` monkeypatched to None → `(Maven not found)`.
- `test_prefers_mvnw`: an executable `mvnw` at the root → command starts with that path.
- `test_no_gaps_no_run`: a complete pom → the runner is never called.

- [ ] **Step 2: Run to verify they fail** — `uv run pytest tests/detectors/test_maven_fallback.py -v` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run to verify they pass** — `uv run pytest -v` → PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat: Maven effective-pom fallback"`

---

### Task 9: End-to-end check against the real API

**Files:**
- Test: `tests/test_end_to_end.py` (marked `@pytest.mark.network`, and skipped unless `EOLCHECKER_NETWORK=1`)
- Modify: `pyproject.toml` (register the `network` marker)

- [ ] **Step 1: Write the test**: build a mixed repo in `tmp_path` and run `main([str(tmp_path), "--no-maven"])` with the real client:
  - `backend/pom.xml`: Boot parent `3.1.5`, `java.version` 17
  - `frontend/package.json`: `@angular/core` `16.2.0`
  - `api/Api.csproj`: `net8.0`
  - `web/composer.json`: `php` `>=7.4`, `laravel/framework` `^10.0`

  Assert exit code 0, and that the output contains every component name, `END OF LIFE` (Spring Boot 3.1 is EOL), and no `unknown`.
- [ ] **Step 2: Run it** — `EOLCHECKER_NETWORK=1 uv run pytest tests/test_end_to_end.py -v` → PASS.
- [ ] **Step 3: Install and smoke-test the real command** — `uv tool install --force .` then `eolchecker /Users/andreaskarlsson/Documents/eolchecker`. Expected: `No supported frameworks found in …` and exit 0.
- [ ] **Step 4: Run the full suite** — `uv run pytest -v` → all PASS (network test skipped).
- [ ] **Step 5: Commit** — `git commit -m "test: end-to-end check against endoflife.date"`
