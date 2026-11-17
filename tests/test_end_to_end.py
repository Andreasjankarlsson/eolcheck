"""Runs the whole tool against the real endoflife.date API. Opt in with EOLCHECKER_NETWORK=1."""
import json
import os

import pytest

from eolchecker.catalogue import load_catalogue
from eolchecker.cli import main

pytestmark = [
    pytest.mark.network,
    pytest.mark.skipif(os.environ.get("EOLCHECKER_NETWORK") != "1", reason="set EOLCHECKER_NETWORK=1 to run"),
]

POM = """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <parent><groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter-parent</artifactId>
  <version>3.1.5</version></parent>
  <artifactId>backend</artifactId>
  <properties><java.version>17</java.version></properties>
  <dependencies>
    <dependency><groupId>org.springframework</groupId><artifactId>spring-core</artifactId><version>6.0.0</version></dependency>
    <dependency><groupId>org.hibernate.orm</groupId><artifactId>hibernate-core</artifactId><version>6.2.0.Final</version></dependency>
  </dependencies>
</project>"""

CSPROJ = '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net8.0</TargetFramework></PropertyGroup></Project>'

PACKAGE_JSON = {"dependencies": {"@angular/core": "16.2.0", "angular": "1.8.2", "react": "18.2.0", "next": "13.5.0"}}

COMPOSER = {"require": {"php": ">=7.4", "laravel/framework": "^10.0", "symfony/http-kernel": "^6.4"}}


def test_mixed_repo_against_real_api(write_files, capsys, tmp_path):
    root = write_files({
        "backend/pom.xml": POM,
        "frontend/package.json": json.dumps(PACKAGE_JSON),
        "web/composer.json": json.dumps(COMPOSER),
        "api/Api.csproj": CSPROJ,
        "Dockerfile": "FROM node:18-bullseye\n",
    })
    sbom = root / "sbom.md"
    cache = tmp_path / "cache.json"
    code = main([str(root), "--no-maven", "--sbom", str(sbom)], catalogue=lambda: load_catalogue(cache))
    assert code == 0
    out = capsys.readouterr().out
    for component in ["Spring Boot", "Spring Framework", "Hibernate ORM", "Angular", "AngularJS", "React",
                      "Next.js", "Laravel", "Symfony", "Node.js", "Debian", "Java", ".NET", "PHP"]:
        assert component in out, component
    assert "END OF LIFE" in out  # Spring Boot 3.1 and Angular 16 are long past end of life
    assert "version not found" not in out
    assert "| Maven | org.springframework.boot:spring-boot-starter-parent | 3.1.5 |" in sbom.read_text()
