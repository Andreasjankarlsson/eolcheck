/** An API-shaped slice of the endoflife.date catalogue, shared by the tests. */
import { Catalogue, parseCatalogue } from "../../src/catalogue.js";

function p(
  name: string,
  label: string,
  purls: string[] = [],
  releases: unknown[] = [],
  aliases: string[] = [],
) {
  return {
    name,
    label,
    aliases,
    identifiers: purls.map((id) => ({ type: "purl", id })),
    releases,
  };
}

function r(
  name: string,
  date: string,
  isEol: boolean,
  eol: string | null,
  latest: string | null,
  codename: string | null = null,
) {
  return { name, releaseDate: date, isEol, eolFrom: eol, latest: { name: latest }, codename };
}

export const FULL = {
  result: [
    p("spring-boot", "Spring Boot",
      ["pkg:maven/org.springframework.boot/spring-boot",
       "pkg:maven/org.springframework.boot/spring-boot-starter-web"],
      [r("4.0", "2025-11-20", false, "2026-12-31", "4.0.1"),
       r("3.2", "2023-11-23", true, "2024-12-31", "3.2.12")]),
    p("spring-framework", "Spring Framework",
      ["pkg:maven/org.springframework/spring-core"],
      [r("6.2", "2024-11-14", false, "2026-06-30", "6.2.1"),
       r("5.3", "2020-10-27", true, "2024-08-31", "5.3.39")]),
    p("hibernate-orm", "Hibernate ORM",
      ["pkg:maven/org.hibernate.orm/hibernate-core",
       "pkg:maven/org.hibernate/hibernate-core"],
      [r("6.6", "2024-08-08", false, "2026-08-08", "6.6.3"),
       r("5.6", "2021-08-05", true, "2023-11-01", "5.6.15")]),
    p("jquery", "jQuery", ["pkg:maven/org.webjars/jquery", "pkg:npm/jquery"],
      [r("3", "2016-06-09", false, null, "3.7.1")]),
    p("jquery-ui", "jQuery UI", ["pkg:maven/org.webjars/jquery-ui"],
      [r("1.13", "2021-10-07", false, null, "1.13.3")]),
    p("angular", "Angular", ["pkg:npm/%40angular/core"],
      [r("20", "2025-05-28", false, "2026-11-28", "20.3.0"),
       r("16", "2023-05-03", true, "2024-11-08", "16.2.12")]),
    p("react", "React", ["pkg:npm/react"],
      [r("19", "2024-12-05", false, null, "19.2.0"),
       r("17", "2020-10-20", false, null, "17.0.2")]),
    p("laravel", "Laravel", ["pkg:composer/laravel/framework"],
      [r("12", "2025-02-24", false, "2027-02-24", "12.1.0"),
       r("10", "2023-02-14", true, "2025-02-04", "10.48.0")]),
    p("symfony", "Symfony", [],
      [r("6.4", "2023-11-29", false, "2027-11-30", "6.4.20"),
       r("2.8", "2015-11-30", true, "2018-11-30", "2.8.52")]),
    p("dotnet", "Microsoft .NET", ["pkg:nuget/Microsoft.NETCore.App"],
      [r("8", "2023-11-14", false, "2026-11-10", "8.0.21"),
       r("6", "2021-11-08", true, "2024-11-12", "6.0.36")],
      ["dotnetcore"]),
    p("dotnetfx", "Microsoft .NET Framework", [],
      [r("4.8", "2019-04-18", false, null, null)]),
    p("nodejs", "Node.js", ["pkg:docker/library/node", "pkg:docker/bitnami/node"],
      [r("22", "2024-04-24", false, "2027-04-30", "22.11.0"),
       r("18", "2022-04-19", true, "2025-04-30", "18.20.5")]),
    p("php", "PHP", [],
      [r("8.3", "2023-11-23", false, "2027-12-31", "8.3.14"),
       r("8.1", "2021-11-25", true, "2025-12-31", "8.1.31")]),
    p("eclipse-temurin", "Eclipse Temurin", [],
      [r("17", "2021-09-14", false, "2027-10-31", "17.0.13")], ["temurin"]),
    p("deno", "Deno", ["pkg:oci/deno?repository_url=ghcr.io/denoland"],
      [r("2", "2024-10-09", false, null, "2.1.4")]),
    p("debian", "Debian", [],
      [r("12", "2023-06-10", false, "2026-06-10", "12.8", "Bookworm"),
       r("11", "2021-08-14", true, "2024-08-14", "11.11", "Bullseye")]),
    p("ubuntu", "Ubuntu", [],
      [r("22.04", "2022-04-21", false, "2027-04-01", "22.04", "Jammy Jellyfish"),
       r("18.04", "2018-04-26", true, "2023-05-31", "18.04", "Bionic Beaver")],
      ["ubuntu-linux"]),
    p("alpine-linux", "Alpine Linux", [],
      [r("3.22", "2025-05-30", false, "2027-05-01", "3.22.2"),
       r("3.19", "2023-12-07", true, "2025-11-01", "3.19.4")],
      ["alpine", "alpinelinux"]),
  ],
};

export function catalogue(): Catalogue {
  return parseCatalogue(FULL);
}
