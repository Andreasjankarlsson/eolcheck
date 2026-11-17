"""An API-shaped slice of the endoflife.date catalogue, shared by the tests."""
from __future__ import annotations

from eolchecker.catalogue import Catalogue, parse_catalogue


def p(name, label, purls=(), aliases=(), releases=()):
    return {
        "name": name,
        "label": label,
        "aliases": list(aliases),
        "identifiers": [{"type": "purl", "id": purl} for purl in purls],
        "releases": list(releases),
    }


def r(name, date, is_eol, eol, latest, codename=None):
    return {
        "name": name,
        "releaseDate": date,
        "isEol": is_eol,
        "eolFrom": eol,
        "latest": {"name": latest},
        "codename": codename,
    }


FULL: dict = {"result": [
    p("spring-boot", "Spring Boot",
      ["pkg:maven/org.springframework.boot/spring-boot",
       "pkg:maven/org.springframework.boot/spring-boot-starter-web"],
      releases=[r("4.0", "2025-11-20", False, "2026-12-31", "4.0.1"),
                r("3.2", "2023-11-23", True, "2024-12-31", "3.2.12")]),
    p("spring-framework", "Spring Framework",
      ["pkg:maven/org.springframework/spring-core"],
      releases=[r("6.2", "2024-11-14", False, "2026-06-30", "6.2.1"),
                r("5.3", "2020-10-27", True, "2024-08-31", "5.3.39")]),
    p("hibernate-orm", "Hibernate ORM",
      ["pkg:maven/org.hibernate.orm/hibernate-core",
       "pkg:maven/org.hibernate/hibernate-core"],
      releases=[r("6.6", "2024-08-08", False, "2026-08-08", "6.6.3"),
                r("5.6", "2021-08-05", True, "2023-11-01", "5.6.15")]),
    p("jquery", "jQuery", ["pkg:maven/org.webjars/jquery", "pkg:npm/jquery"],
      releases=[r("3", "2016-06-09", False, None, "3.7.1")]),
    p("jquery-ui", "jQuery UI", ["pkg:maven/org.webjars/jquery-ui"],
      releases=[r("1.13", "2021-10-07", False, None, "1.13.3")]),
    p("angular", "Angular", ["pkg:npm/%40angular/core"],
      releases=[r("20", "2025-05-28", False, "2026-11-28", "20.3.0"),
                r("16", "2023-05-03", True, "2024-11-08", "16.2.12")]),
    p("react", "React", ["pkg:npm/react"],
      releases=[r("19", "2024-12-05", False, None, "19.2.0"),
                r("17", "2020-10-20", False, None, "17.0.2")]),
    p("laravel", "Laravel", ["pkg:composer/laravel/framework"],
      releases=[r("12", "2025-02-24", False, "2027-02-24", "12.1.0"),
                r("10", "2023-02-14", True, "2025-02-04", "10.48.0")]),
    p("symfony", "Symfony",
      releases=[r("6.4", "2023-11-29", False, "2027-11-30", "6.4.20"),
                r("2.8", "2015-11-30", True, "2018-11-30", "2.8.52")]),
    p("dotnet", "Microsoft .NET", ["pkg:nuget/Microsoft.NETCore.App"],
      aliases=["dotnetcore"],
      releases=[r("8", "2023-11-14", False, "2026-11-10", "8.0.21"),
                r("6", "2021-11-08", True, "2024-11-12", "6.0.36")]),
    p("dotnetfx", "Microsoft .NET Framework",
      releases=[r("4.8", "2019-04-18", False, None, None)]),
    p("nodejs", "Node.js", ["pkg:docker/library/node", "pkg:docker/bitnami/node"],
      releases=[r("22", "2024-04-24", False, "2027-04-30", "22.11.0"),
                r("18", "2022-04-19", True, "2025-04-30", "18.20.5")]),
    p("php", "PHP",
      releases=[r("8.3", "2023-11-23", False, "2027-12-31", "8.3.14"),
                r("8.1", "2021-11-25", True, "2025-12-31", "8.1.31")]),
    p("eclipse-temurin", "Eclipse Temurin", aliases=["temurin"],
      releases=[r("17", "2021-09-14", False, "2027-10-31", "17.0.13")]),
    p("deno", "Deno", ["pkg:oci/deno?repository_url=ghcr.io/denoland"],
      releases=[r("2", "2024-10-09", False, None, "2.1.4")]),
    p("debian", "Debian",
      releases=[r("12", "2023-06-10", False, "2026-06-10", "12.8", "Bookworm"),
                r("11", "2021-08-14", True, "2024-08-14", "11.11", "Bullseye")]),
    p("ubuntu", "Ubuntu", aliases=["ubuntu-linux"],
      releases=[r("22.04", "2022-04-21", False, "2027-04-01", "22.04", "Jammy Jellyfish"),
                r("18.04", "2018-04-26", True, "2023-05-31", "18.04", "Bionic Beaver")]),
    p("alpine-linux", "Alpine Linux", aliases=["alpine", "alpinelinux"],
      releases=[r("3.22", "2025-05-30", False, "2027-05-01", "3.22.2"),
                r("3.19", "2023-12-07", True, "2025-11-01", "3.19.4")]),
]}


def catalogue() -> Catalogue:
    return parse_catalogue(FULL)
