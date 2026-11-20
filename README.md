# eolchecker

Checks whether the dependencies in a cloned repo are past end-of-life,
using dates from [endoflife.date](https://endoflife.date).

The dependencies come from each ecosystem's own CycloneDX SBOM plugin (Maven,
npm, .NET, Composer), which eolchecker runs for you. It works from the command
line, as a Jenkins step, and as a library (for example in an Electron app).

## Install

Needs Node.js 24 or newer. The package isn't published to a registry, so
install it from a checkout:

```sh
npm install
npm run build
npm install -g .        # puts `eolchecker` on your PATH
```

Then run `eolchecker <folder>`, or `npx eolchecker <folder>` in a project that
has eolchecker as a dependency.

### Toolchains

eolchecker doesn't install toolchains. It uses the ones on your `PATH`:

| Ecosystem | Needs |
|---|---|
| Maven | JDK and Maven (`./mvnw` is used when the repo has one). Maven downloads the CycloneDX plugin `org.cyclonedx:cyclonedx-maven-plugin:2.9.1` on first use, like any other plugin. |
| npm | Node.js and npm. The npm plugin (`@cyclonedx/cyclonedx-npm` 7.0.1) ships with eolchecker. |
| .NET | The .NET SDK (and the SDK version a `global.json` asks for), plus the CycloneDX .NET tool. |
| Composer | PHP 8.1+ and Composer, plus the Composer CycloneDX plugin. |

Two one-time installs:

```sh
dotnet tool install --global CycloneDX --version 6.3.1
composer global config --no-plugins allow-plugins.cyclonedx/cyclonedx-php-composer true \
  && composer global require cyclonedx/cyclonedx-php-composer:6.2.0
```

`dotnet tool install --global` puts the tool in `~/.dotnet/tools`. Make sure
that folder is on your `PATH`, or eolchecker reports
`not scanned (CycloneDX .NET tool not found)`.

A missing toolchain never stops the run. The projects that need it are listed
under "Not recognised", for example `backend/pom.xml: not scanned (Maven not found)`,
and the install command is printed for the two one-time installs.

## Use

```sh
eolchecker ~/code/some-repo
eolchecker ~/code/some-repo --sbom out.csv    # also write every dependency to out.csv or out.md
eolchecker ~/code/some-repo --json            # print the report as JSON instead of the table
```

| Flag | Meaning |
|---|---|
| `--sbom FILE` | Also write every dependency, tracked or not, to `FILE`. Must end in `.csv` or `.md`. |
| `--json` | Print the report as JSON on stdout instead of the table. Progress lines and "SBOM written to …" go to stderr, so stdout stays valid JSON. |
| `-h`, `--help` | Show help. |

Exit codes: `0` when the scan finished, whatever it found; `1` when the
endoflife.date catalogue can't be loaded, `--sbom` can't be written, or the scan
fails unexpectedly; `2` for bad arguments, a path that doesn't exist or isn't a
folder, or an `--sbom` file that doesn't end in `.csv`/`.md`. END OF LIFE
findings never change the exit code. To fail a build on them, read the JSON.

It needs internet access to fetch the dates. The full endoflife.date catalogue
is cached in `~/Library/Caches/eolchecker/products-full.json` (on Linux
`$XDG_CACHE_HOME/eolchecker/`, or `~/.cache/eolchecker/` when that isn't set)
and refreshed after 24 hours. If endoflife.date can't be reached, a cached copy
of any age is used and a warning says how old it is; with no cached copy the
run stops with an error.

For each product it finds, it shows the version in use, the file it came
from, the end-of-support date, the newest release, and a status:
`END OF LIFE`, `supported`, `no EOL date` (the project publishes no dates,
e.g. React), or `version not found` (endoflife.date tracks the product, but
the version matches no release cycle). Files that couldn't be read or scanned
are listed under "Not recognised" with the reason.

### JSON output

`--json` prints one object:

```json
{
  "rows":         [{ "component": "", "version": "", "foundIn": "", "endOfSupport": "", "latest": "", "status": "" }],
  "sbom":         [{ "ecosystem": "", "name": "", "version": "", "foundIn": "", "product": "", "endOfSupport": "", "status": "" }],
  "unrecognised": [{ "source": "", "reason": "" }],
  "hints":        [""]
}
```

- `rows`: the terminal table, one entry per product, version and file.
  `status` is `END OF LIFE`, `supported`, `no EOL date` or `version not found`.
  `endOfSupport` and `latest` are `—` when there is no value.
- `sbom`: every dependency and runtime, the same as `--sbom`. `ecosystem` is
  `Maven`, `npm`, `NuGet`, `Composer`, `Docker` or `Runtime`. `product`,
  `endOfSupport` and `status` are empty strings for dependencies endoflife.date
  doesn't track.
- `unrecognised`: "Not recognised" lines; `source` is the file, `reason` the text,
  e.g. `not scanned (no lock file)`.
- `hints`: one-time install commands for a missing .NET tool or Composer plugin.

All paths are relative to the scanned folder, with `/` separators. When nothing
is found, all four lists are empty.

### Jenkins

Run eolchecker after the build, on an agent that has eolchecker installed and the
toolchains the repo needs:

```sh
npx eolchecker . --json > eol-report.json
```

Maven fetches the CycloneDX plugin like any other plugin, so the agent needs the
same Maven settings (proxy, mirror) as its builds. Offline with an empty local
repository, Maven projects show as `not scanned (Maven failed: …)`.

### As a library

```ts
import { scan, renderTable, writeSbom, ApiUnavailable, type Report } from "eolchecker";

const controller = new AbortController();
const report: Report = await scan("/path/to/repo", {
  cacheDir: app.getPath("userData"),   // where products-full.json is cached
  env: shellEnv,                       // must include a PATH with mvn, npm, dotnet, ~/.dotnet/tools, composer
  onProgress: (msg) => console.log(msg),
  warn: (msg) => console.warn(msg),    // e.g. "using a cached copy from …"
  signal: controller.signal,           // cancels running tools
});
```

`scan` never prints and never exits the process. It throws `ApiUnavailable` when
the catalogue can't be loaded. `report` has the same shape as the JSON output.
`renderTable(title, report, { color })` gives the terminal table as text, and
`writeSbom(path, report.sbom)` writes the `.csv`/`.md` file.

In Electron, call `scan` from the main process. Apps started from the macOS Dock
don't get your shell's `PATH`, so they won't find `mvn`, `npm`, `dotnet` or
`composer` unless you pass `env`. Loading the login shell's environment is up to
the app. `env` defaults to `process.env`, `cacheDir` to the CLI's cache folder.

## What it checks

Any product endoflife.date tracks. Dependencies are matched from their package
URLs and image names (Maven, npm, Composer, NuGet, Docker) plus a few general
rules (see the design specs in `docs/superpowers/specs/`). Runtimes have their
own rules: Java, Node.js, PHP, .NET and .NET Framework. Image tags that pin an
OS (e.g. `bullseye`) add an OS row such as Debian 11.

| Files | How |
|---|---|
| `pom.xml` | The CycloneDX Maven plugin, once per reactor (the top-most `pom.xml`), all scopes including `test`. Java comes from the effective pom (`maven.compiler.release`/`source`, `java.version`, compiler plugin `release`/`source`). |
| `package.json` with a `package-lock.json` | The CycloneDX npm plugin, from the lock file (or from `node_modules` when installed). `dependencies`, `devDependencies`, `peerDependencies`. Workspace members are scanned too. Node.js comes from `engines.node`, `.nvmrc` and `.node-version`. |
| `*.csproj`, `*.fsproj`, `*.vbproj` | The CycloneDX .NET tool, per project, which also reads `packages.config` and central package versions. Target frameworks come from `dotnet msbuild -getProperty`, so `Directory.Build.props` and conditions apply; if that fails, from the project file alone. `global.json` gives the SDK version. |
| `composer.json` with a `composer.lock` | The Composer CycloneDX plugin, `require` and `require-dev`. PHP comes from `config.platform.php`, else `require.php`. |
| Dockerfiles, compose files | Read directly: `FROM` lines, `ARG` and compose defaults. |

Only declared (direct) dependencies are checked, not transitive ones. Versions
are the resolved ones from the lock file or the build tool, never ranges.
Folders named `.git`, `node_modules`, `vendor`, `target`, `build`, `dist`,
`bin`, `obj`, `.idea` and `.venv` are skipped. Gradle files and CI configs are
not read.

The terminal table shows only what endoflife.date tracks. `--sbom` lists every
dependency, tracked or not.

### Not scanned

These are listed under "Not recognised" instead of being guessed:

- `package.json` or `composer.json` without a lock file: `not scanned (no lock file)`.
  eolchecker never runs `npm install` or `composer install`.
- yarn and pnpm projects (nearest lock file is `yarn.lock` or `pnpm-lock.yaml`):
  `not scanned (yarn/pnpm not supported)`. Their Node.js version is still read.
- Missing toolchain: `not scanned (<tool> not found)`.
- A tool that fails or takes longer than 3 minutes:
  `not scanned (<tool> failed: <first line of its error output>)` or
  `not scanned (<tool> timed out)`.

## Side effects

A scan behaves like a normal developer build of the repo:

- Maven writes `target/eolchecker-bom.json` in each module and may fill `~/.m2`.
- The .NET tool runs a NuGet restore, which writes `obj/` and may fill the NuGet cache.
- Other plugin output goes to a temporary folder that is removed afterwards.

eolchecker never changes tracked files. `target/` and `obj/` are build folders
that repos normally ignore.

## Known gaps

- `org.apache.tomcat.embed:tomcat-embed-core` is not in the catalogue, so Tomcat declared that way is not reported.
- `mcr.microsoft.com/dotnet/*` images are not recognised. The .NET version is usually also visible through the project files' target framework.
- Company-registry base images (e.g. `registry.example.com/java-base:17`) appear in the SBOM untracked; only their OS row (when the tag names one) carries a status.
- A rule match can still be wrong for a package with its own numbering in a shared group or vendor (e.g. an old `org.hibernate:hibernate-validator` alone in a pom would read as Hibernate ORM).
- When the SDK a `global.json` asks for isn't installed, `dotnet msbuild` can't evaluate the projects, so a target framework set only in `Directory.Build.props` isn't found and the projects aren't scanned for packages.
- Maven `<parent>` and `<dependencyManagement>` entries aren't dependencies, so they don't get rows. Spring Boot is found through its starters.
- macOS and Linux only; not tested on Windows.

## Development

```sh
npm install
npm test                                   # unit tests, no network, no real tools
npm run build                              # compiles to dist/
EOLCHECKER_TOOLS=1 npx vitest run test/tools.integration.test.ts       # runs the real Maven/npm/.NET/Composer plugins on test/fixtures/projects
EOLCHECKER_NETWORK=1 npx vitest run test/network.integration.test.ts   # against the real endoflife.date API
```

The integration tests skip ecosystems whose tool isn't installed. The Python
version in `src/eolchecker/` is still in the repo until the TypeScript version
replaces it; `docs/parity-notes.md` compares the two.
