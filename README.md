# eolchecker

Checks whether the dependencies in a cloned repo are past end-of-life,
using dates from [endoflife.date](https://endoflife.date).

## Install

```sh
uv tool install .
```

## Use

```sh
eolchecker ~/code/some-repo
eolchecker ~/code/some-repo --no-maven   # don't run Maven for versions inherited from parent poms
eolchecker ~/code/some-repo --sbom out.md   # also write every dependency to out.csv or out.md
```

It needs internet access to fetch the dates. The full endoflife.date catalogue
is cached in `~/Library/Caches/eolchecker/products-full.json` (on Linux
`~/.cache/eolchecker/`) and refreshed after 24 hours.

For each product it finds, it shows the version in use, the file it came
from, the end-of-support date, the newest release, and a status:
`END OF LIFE`, `supported`, `no EOL date` (the project publishes no dates,
e.g. React), or `version not found` (endoflife.date tracks the product, but
the version matches no release cycle). Files where a framework is clearly used
but the version can't be read are listed under "Not recognised".

## What it checks

Any product endoflife.date tracks. Dependencies are matched from their
package and image names (Maven, npm, Composer, NuGet, Docker) plus a few
general rules (see the design spec in `docs/superpowers/specs/`). Runtimes
have their own rules: Java, Node.js, PHP, .NET and .NET Framework. Image
tags that pin an OS (e.g. `bullseye`) add an OS row such as Debian 11.

It reads `pom.xml`, `package.json` (plus lock files), `.nvmrc`,
`.node-version`, `composer.json`/`composer.lock`, `*.csproj`/`*.fsproj`/`*.vbproj`
(`PackageReference`), `Directory.Build.props`, `Directory.Packages.props`,
`packages.config`, `global.json`, Dockerfiles and compose files. It does not
read Gradle files or CI configs. Only declared dependencies are checked, not
transitive ones. If a Maven dependency is declared without a version, the
tool asks Maven for it.

The terminal table shows only what endoflife.date tracks. `--sbom` lists every
declared dependency, tracked or not.

## Known gaps

- `org.apache.tomcat.embed:tomcat-embed-core` is not in the catalogue, so Tomcat declared that way is not reported.
- `mcr.microsoft.com/dotnet/*` images are not recognised. The .NET version is usually also visible through the project files' target framework.
- Company-registry base images (e.g. `registry.example.com/java-base:17`) appear in the SBOM untracked; only their OS row (when the tag names one) carries a status.
- A rule match can still be wrong for a package with its own numbering in a shared group or vendor (e.g. an old `org.hibernate:hibernate-validator` alone in a pom would read as Hibernate ORM).

## Development

```sh
uv run pytest
EOLCHECKER_NETWORK=1 uv run pytest tests/test_end_to_end.py   # against the real API
```
