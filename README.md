# eolchecker

Checks whether the dependencies in a cloned repo are past end-of-life, using
dates from [endoflife.date](https://endoflife.date). It checks every direct
dependency that endoflife.date tracks, plus the Java, Node.js, PHP and .NET
versions the repo targets.

## Install

You need [uv](https://docs.astral.sh/uv/). It fetches Python 3.11 or newer if
you don't have it.

Maven (or a `mvnw` in the project you scan) is optional. It is only used to
find versions that are inherited from parent poms.

```sh
git clone <repo-url>
cd eolchecker
uv sync
```

## Run

From the checkout:

```sh
uv run eolchecker ~/code/some-repo
```

Options:

- `--no-maven`: don't run Maven to resolve versions inherited from parent poms.
- `--csv results.csv`: also write the results to a CSV file.
- `--show-untracked`: also list dependencies that endoflife.date doesn't track.
- `--refresh`: ignore the cached endoflife.date data and download it again.

It needs internet access to fetch the dates (see "Cache and config" for what
happens when you are offline).

Example output (shortened):

| Component     | Dependencies                          | Version            | Found in     | End of support | Latest | Status      |
|---------------|---------------------------------------|--------------------|--------------|----------------|--------|-------------|
| Spring Boot   | spring-boot-starter-web, spring-boot-starter-test | 3.2.0 (also 3.4.1) | pom.xml | 2024-12-31 | 3.5.0  | END OF LIFE |
| Java          | maven.compiler.release                | 21                 | pom.xml      | 2029-09-30     | 25     | supported   |
| Angular       | @angular/core, @angular/common        | 17.3.0             | package.json | 2025-05-15     | 20.0.0 | END OF LIFE |

The table above is only an example. The dates and versions are made up.

What the statuses mean:

- `END OF LIFE`: the end-of-support date has passed.
- `supported`: the end-of-support date is still ahead.
- `no EOL date`: the project publishes no dates (for example React).
- `unknown version`: endoflife.date knows the product, but not this version line.
- `not tracked`: endoflife.date doesn't track the dependency. Shown only with
  `--show-untracked` (and in the CSV).
- `not recognised`: only in the CSV. In the table these are listed under
  "Not recognised": files where a tracked dependency is clearly used but its
  version can't be read.

To install it as a command instead, run `uv tool install .` and then use
`eolchecker ~/code/some-repo`. The cache then lives in your user cache folder
(`~/Library/Caches/eolchecker` on macOS, `~/.cache/eolchecker` elsewhere).

## Cache and config

The endoflife.date data is cached in `.cache/products-full.json` inside the
checkout (the folder is git-ignored). Every run checks whether endoflife.date
has changed and only downloads the data again if it has. If endoflife.date
can't be reached, the cached copy is used and a line says how old it is.

To keep the cache somewhere else, create `eolchecker.toml` in the checkout:

```toml
cache_dir = "some/other/folder"   # relative to the checkout
```

## What it checks

Every direct dependency is matched against the package identifiers (purls)
that endoflife.date publishes for its products. This covers npm, Maven,
Composer and NuGet packages. On top of that it reads the Java, Node.js, PHP
and .NET versions the repo uses.

Only direct dependencies are checked, including dev, test and plugin
dependencies. Lock files are only used to get the exact version of a direct
dependency. They are never used to find more packages.

You get one row per product per file. If several dependencies of the same
product have different versions, the lowest one is checked and the others are
shown as `(also …)`.

When a pom declares a tracked dependency without a version, and only Spring
Boot or a BOM sets it, the tool asks Maven for the effective pom of that pom.
In a multi-module repo this can mean one Maven run per module. `--no-maven`
turns this off, and those dependencies are then listed under "Not recognised".

Files it reads: `pom.xml`, `package.json` (plus lock files), `.nvmrc`,
`.node-version`, `composer.json` and `composer.lock`, `*.csproj`, `*.fsproj`,
`*.vbproj`, `packages.config`, `Directory.Build.props`,
`Directory.Packages.props` and `global.json`.

It does not read Gradle files, Dockerfiles or CI configs.

## Development

```sh
uv run pytest
EOLCHECKER_NETWORK=1 uv run pytest tests/test_end_to_end.py   # against the real API
```
