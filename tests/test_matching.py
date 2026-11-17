from pathlib import Path

import pytest

from eolchecker.matching import (
    Match, Matcher, OsHit, docker_purl, is_official_image, normalise_purl, os_from_tag,
)
from eolchecker.models import Dependency

from .catalogue_fixture import catalogue


@pytest.mark.parametrize("raw, expected", [
    ("pkg:npm/%40angular/core", "pkg:npm/@angular/core"),
    ("pkg:npm/React@18.2.0", "pkg:npm/react"),
    ("pkg:maven/org.Foo/Bar@1.0?type=jar", "pkg:maven/org.Foo/Bar"),
    ("pkg:nuget/Microsoft.NETCore.App", "pkg:nuget/microsoft.netcore.app"),
    ("pkg:oci/deno?repository_url=ghcr.io/denoland", "pkg:oci/deno?repository_url=ghcr.io/denoland"),
    ("pkg:docker/library/node?tag=18", "pkg:docker/library/node"),
])
def test_normalise_purl(raw, expected):
    assert normalise_purl(raw) == expected


@pytest.mark.parametrize("image, expected", [
    ("node", "pkg:docker/library/node"),
    ("docker.io/library/node", "pkg:docker/library/node"),
    ("index.docker.io/bitnami/node", "pkg:docker/bitnami/node"),
    ("ghcr.io/denoland/deno", "pkg:oci/deno?repository_url=ghcr.io/denoland"),
    ("localhost:5000/app", "pkg:oci/app?repository_url=localhost:5000"),
])
def test_docker_purl(image, expected):
    assert docker_purl(image) == expected


def test_official_image():
    assert is_official_image("php") and is_official_image("library/php") and is_official_image("docker.io/php")
    assert not is_official_image("myorg/php") and not is_official_image("ghcr.io/x/php")


M = Matcher(catalogue())


def dep(eco, name):
    return Dependency(eco, name, "1.0", "1.0", Path("f"))


@pytest.mark.parametrize("eco, name, expected", [
    ("npm", "@angular/core", Match("angular", False)),
    ("npm", "React", Match("react", False)),
    ("Maven", "org.springframework.boot:spring-boot-starter-web", Match("spring-boot", False)),
    ("Maven", "org.springframework.boot:spring-boot-starter-parent", Match("spring-boot", True)),
    ("Maven", "org.hibernate:hibernate-core", Match("hibernate-orm", False)),
    ("NuGet", "microsoft.netcore.app", Match("dotnet", False)),
    ("Composer", "laravel/framework", Match("laravel", False)),
    ("Composer", "symfony/http-kernel", Match("symfony", True)),
    ("Docker", "node", Match("nodejs", False)),
    ("Docker", "ghcr.io/denoland/deno", Match("deno", False)),
    ("Docker", "php", Match("php", True)),
    ("Docker", "alpine", Match("alpine-linux", True)),
    ("Docker", "eclipse-temurin", Match("eclipse-temurin", True)),
])
def test_matches(eco, name, expected):
    assert M.match(dep(eco, name)) == expected


@pytest.mark.parametrize("eco, name", [
    ("Maven", "org.springframework.data:spring-data-jpa"),
    ("Maven", "org.webjars:bootstrap"),
    ("Composer", "laravel/sanctum"),
    ("Docker", "myorg/php"),
    ("Docker", "registry.example.com/java-base"),
    ("npm", "left-pad"),
])
def test_no_match(eco, name):
    assert M.match(dep(eco, name)) is None


@pytest.mark.parametrize("tag, hits", [
    ("18-alpine3.19", [OsHit("alpine-linux", "3.19", "3.19")]),
    ("18-bullseye", [OsHit("debian", "11", "11 (bullseye)")]),
    ("3.12-slim-Bookworm", [OsHit("debian", "12", "12 (bookworm)")]),
    ("17-jre-jammy", [OsHit("ubuntu", "22.04", "22.04 (jammy)")]),
    ("bookworm-slim", [OsHit("debian", "12", "12 (bookworm)")]),
    ("8.3-fpm", []),
    ("latest", []),
])
def test_os_from_tag(tag, hits):
    assert os_from_tag(tag, catalogue()).hits == hits


def test_unpinned_alpine():
    reading = os_from_tag("18-alpine", catalogue())
    assert reading.hits == [] and reading.missing == [("alpine-linux", "Alpine version not pinned")]
