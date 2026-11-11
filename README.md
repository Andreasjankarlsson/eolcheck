# eolchecker

Checks whether the major frameworks in a cloned repo are past end-of-life,
using dates from [endoflife.date](https://endoflife.date). It only looks at the
big ones, not every small library.

## Install

```sh
uv tool install .
```

## Use

```sh
eolchecker ~/code/some-repo
eolchecker ~/code/some-repo --no-maven   # don't run Maven for versions inherited from parent poms
```

It needs internet access to fetch the dates.

For each framework it finds, it shows the version in use, the file it came
from, the end-of-support date, the newest release, and a status:
`END OF LIFE`, `supported`, `no EOL date` (the project publishes no dates,
e.g. React), or `unknown`. Files where a framework is clearly used but the
version can't be read are listed under "Not recognised".

## What it checks

Spring Boot, Spring Framework, Java, Hibernate ORM, Apache Tomcat,
.NET, .NET Framework, Angular, AngularJS, React, Next.js, Node.js,
PHP, Laravel, Symfony.

Spring Framework, Hibernate ORM and Tomcat are only reported when a `pom.xml` declares
them, not when they come in transitively through a Spring Boot starter. If one is declared
without a version (Spring Boot picks it), the tool asks Maven for the version.

It reads `pom.xml`, `package.json` (plus lock files), `.nvmrc`,
`.node-version`, `composer.json`/`composer.lock`, `*.csproj`/`*.fsproj`/`*.vbproj`,
`Directory.Build.props` and `global.json`. It does not read Gradle files,
Dockerfiles or CI configs.

## Development

```sh
uv run pytest
EOLCHECKER_NETWORK=1 uv run pytest tests/test_end_to_end.py   # against the real API
```
