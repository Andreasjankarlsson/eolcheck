"""Runs the whole tool against the real endoflife.date API. Opt in with EOLCHECKER_NETWORK=1."""
import json
import os

import pytest

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
</project>"""

CSPROJ = '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net8.0</TargetFramework></PropertyGroup></Project>'


def test_mixed_repo_against_real_api(write_files, capsys):
    root = write_files({
        "backend/pom.xml": POM,
        "frontend/package.json": json.dumps({"dependencies": {"@angular/core": "16.2.0"}}),
        "api/Api.csproj": CSPROJ,
        "web/composer.json": json.dumps({"require": {"php": ">=7.4", "laravel/framework": "^10.0"}}),
    })
    assert main([str(root), "--no-maven"]) == 0
    out = capsys.readouterr().out
    for component in ["Spring Boot", "Java", "Angular", ".NET", "PHP", "Laravel"]:
        assert component in out
    assert "END OF LIFE" in out  # Spring Boot 3.1 and Angular 16 are long past end of life
    assert "unknown" not in out
