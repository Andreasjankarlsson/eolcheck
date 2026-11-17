from pathlib import Path

from eolchecker.catalogue import parse_catalogue
from eolchecker.models import DetectResult, Dependency, Unrecognised, finding
from eolchecker.rows import Row, SbomRow, _tidy, build_report

from . import catalogue_fixture
from .catalogue_fixture import catalogue, p, r

POM = Path("pom.xml")
PKG = Path("package.json")
COMPOSER = Path("composer.json")
DOCKERFILE = Path("Dockerfile")


def maven(name, version, source=POM, missing=None, via_maven=False):
    return Dependency("Maven", name, version, version or "set by parent pom", source,
                      via_maven=via_maven, missing=missing)


def composer(name, version):
    return Dependency("Composer", name, version, version, COMPOSER)


def docker(name, tag, version, missing=None):
    return Dependency("Docker", name, version, tag, DOCKERFILE, missing=missing, tag=tag)


def report(findings=(), dependencies=(), unrecognised=(), cat=None):
    result = DetectResult(list(findings), list(dependencies), list(unrecognised))
    return build_report(result, cat or catalogue())


# --- status rules -------------------------------------------------------------------

def test_eol_row():
    rep = report(dependencies=[maven("org.springframework.boot:spring-boot", "3.2.5", Path("backend/pom.xml"))])
    assert rep.rows == [Row("Spring Boot", "3.2.5", "backend/pom.xml", "2024-12-31", "4.0.1", "END OF LIFE")]


def test_major_only_cycle():
    [row] = report(findings=[finding(".NET", "8.0", "net8.0", Path("api/Api.csproj"))]).rows
    assert (row.component, row.status, row.end_of_support) == (".NET", "supported", "2026-11-10")


def test_no_eol_date():
    [row] = report(dependencies=[Dependency("npm", "react", "17.0.2", "17.0.2", PKG)]).rows
    assert (row.status, row.end_of_support, row.latest) == ("no EOL date", "—", "19.2.0")


def test_latest_drops_build_metadata():
    cat = parse_catalogue({"result": [p("eclipse-temurin", "Eclipse Temurin", releases=[
        r("27", "2026-09-15", False, "2027-03-23", "27.0.1.0.2+1"),
        r("17", "2021-09-14", False, "2029-09-30", "17.0.13+11")])]})
    [row] = report(findings=[finding("Java", "17", "17", POM)], cat=cat).rows
    assert row.latest == "27.0.1"


def test_tidy_keeps_normal_versions():
    assert _tidy("4.8.1") == "4.8.1"
    assert _tidy("27.0.1.0.2+1") == "27.0.1"


def test_version_not_found():
    [row] = report(dependencies=[Dependency("npm", "react", "15.0.0", "15.0.0", PKG)]).rows
    assert (row.component, row.status, row.end_of_support) == ("React", "version not found", "—")


def test_runtime_slug_missing_from_catalogue():
    cat = parse_catalogue({"result": []})
    rep = report(findings=[finding("PHP", "8.1", "8.1", COMPOSER)], cat=cat)
    assert rep.rows == [Row("PHP", "8.1", "composer.json", "—", "—", "version not found")]
    assert rep.sbom == [SbomRow("Runtime", "PHP", "8.1", "composer.json", "", "", "version not found")]


def test_via_maven_suffix():
    [row] = report(dependencies=[maven("org.springframework.boot:spring-boot", "3.2.5", Path("api/pom.xml"),
                                       via_maven=True)]).rows
    assert row.found_in == "api/pom.xml (via Maven)"


# --- table rows -------------------------------------------------------------------

def test_runtime_rows_bypass_merge():
    src = Path("Api.csproj")
    rows = report(findings=[finding(".NET", "6.0", "net6.0", src), finding(".NET", "8.0", "net8.0", src)]).rows
    assert [(r.component, r.version, r.status) for r in rows] == [
        (".NET", "net6.0", "END OF LIFE"), (".NET", "net8.0", "supported")]


def test_exact_matches_take_lowest():
    rows = report(dependencies=[maven("org.springframework.boot:spring-boot-starter-web", "4.0.1"),
                                maven("org.springframework.boot:spring-boot", "3.2.0")]).rows
    assert [(r.component, r.version, r.status) for r in rows] == [("Spring Boot", "3.2.0", "END OF LIFE")]


def test_versionless_members_do_not_decide():
    rep = report(dependencies=[
        maven("org.springframework.boot:spring-boot-starter-parent", "3.2.0"),
        maven("org.springframework.boot:spring-boot-starter-web", None, missing="set by parent pom"),
    ])
    assert [(r.component, r.version) for r in rep.rows] == [("Spring Boot", "3.2.0")]
    assert rep.unrecognised == []


def test_missing_version_one_line_per_product():
    rep = report(dependencies=[
        maven("org.springframework.boot:spring-boot-starter-web", None, missing="set by parent pom"),
        maven("org.springframework.boot:spring-boot", None, missing="set by parent pom"),
    ])
    assert rep.unrecognised == [Unrecognised(POM, "couldn't read the Spring Boot version (set by parent pom)")]
    assert rep.rows == []


def test_rule_matches_use_most_common_version():
    rows = report(dependencies=[composer("symfony/http-kernel", "6.4.1"), composer("symfony/console", "6.4.3"),
                                composer("symfony/polyfill-mbstring", "1.28.0")]).rows
    assert [(r.component, r.version, r.status) for r in rows] == [("Symfony", "6.4.1", "supported")]


def test_untracked_not_in_table_but_in_sbom():
    rep = report(dependencies=[Dependency("npm", "left-pad", "1.3.0", "1.3.0", PKG)])
    assert rep.rows == []
    assert rep.sbom == [SbomRow("npm", "left-pad", "1.3.0", "package.json", "", "", "")]


# --- Docker -------------------------------------------------------------------

def test_docker_product_and_os_rows():
    rep = report(dependencies=[docker("node", "18-bullseye", "18")])
    assert [(r.component, r.version, r.status) for r in rep.rows] == [
        ("Debian", "11 (bullseye)", "END OF LIFE"), ("Node.js", "18-bullseye", "END OF LIFE")]
    assert rep.sbom == [
        SbomRow("Docker", "Debian", "11 (bullseye)", "Dockerfile", "Debian", "2024-08-14", "END OF LIFE"),
        SbomRow("Docker", "node", "18-bullseye", "Dockerfile", "Node.js", "2025-04-30", "END OF LIFE"),
    ]
    assert rep.unrecognised == []


def test_os_image_single_row():
    rep = report(dependencies=[docker("debian", "bookworm-slim", None, missing="image tag doesn't pin a version")])
    assert [(r.component, r.version, r.status) for r in rep.rows] == [("Debian", "12 (bookworm)", "supported")]
    assert rep.unrecognised == []
    assert rep.sbom == [
        SbomRow("Docker", "debian", "12 (bookworm)", "Dockerfile", "Debian", "2026-06-10", "supported")]


def test_os_image_with_numeric_tag_single_sbom_row():
    rep = report(dependencies=[docker("debian", "12-bookworm", "12")])
    assert [(r.component, r.version) for r in rep.rows] == [("Debian", "12-bookworm")]
    assert rep.sbom == [
        SbomRow("Docker", "debian", "12-bookworm", "Dockerfile", "Debian", "2026-06-10", "supported")]


def test_os_product_missing_from_catalogue_is_skipped():
    cat = parse_catalogue({"result": [p for p in catalogue_fixture.FULL["result"] if p["name"] != "alpine-linux"]})
    for tag in ("18-alpine", "18-alpine3.19"):
        rep = report(dependencies=[docker("node", tag, "18")], cat=cat)
        assert [r.component for r in rep.rows] == ["Node.js"]
        assert rep.unrecognised == []
        assert [s.name for s in rep.sbom] == ["node"]


def test_unknown_image_still_gets_os_row():
    rep = report(dependencies=[docker("registry.example.com/java-base", "17-jammy", "17")])
    assert [(r.component, r.version) for r in rep.rows] == [("Ubuntu", "22.04 (jammy)")]
    image = next(s for s in rep.sbom if s.name == "registry.example.com/java-base")
    assert (image.product, image.end_of_support, image.status) == ("", "", "")


def test_multi_stage_dockerfile_keeps_every_sbom_row():
    rep = report(dependencies=[docker("node", "18-bullseye", "18"), docker("python", "3.12-slim-bookworm", "3.12"),
                               docker("debian", "12-bookworm", "12"), docker("node", "22-alpine", "22")])
    assert sorted((s.name, s.version, s.status) for s in rep.sbom) == [
        ("Debian", "11 (bullseye)", "END OF LIFE"),
        ("Debian", "12 (bookworm)", "supported"),
        ("debian", "12-bookworm", "supported"),
        ("node", "18-bullseye", "END OF LIFE"),
        ("node", "22-alpine", "supported"),
        ("python", "3.12-slim-bookworm", ""),
    ]


def test_unpinned_alpine_is_unrecognised():
    rep = report(dependencies=[docker("node", "18-alpine", "18")])
    assert [r.component for r in rep.rows] == ["Node.js"]
    assert rep.unrecognised == [
        Unrecognised(DOCKERFILE, "couldn't read the Alpine Linux version (Alpine version not pinned)")]


# --- SBOM -------------------------------------------------------------------

def test_sbom_rule_match_outside_chosen_cycle_has_blank_status():
    sbom = report(dependencies=[composer("symfony/http-kernel", "6.4.1"), composer("symfony/console", "6.4.3"),
                                composer("symfony/flex", "2.8.0")]).sbom
    by_name = {s.name: s for s in sbom}
    assert by_name["symfony/flex"] == SbomRow("Composer", "symfony/flex", "2.8.0", "composer.json", "Symfony", "", "")
    assert by_name["symfony/http-kernel"].status == "supported"


def test_sbom_exact_rows_use_own_version():
    rep = report(dependencies=[maven("org.hibernate:hibernate-core", "5.6.15"),
                               maven("org.hibernate:hibernate-validator", "6.6.0")])
    assert [(r.component, r.version, r.status) for r in rep.rows] == [("Hibernate ORM", "5.6.15", "END OF LIFE")]
    by_name = {s.name: s for s in rep.sbom}
    assert by_name["org.hibernate:hibernate-core"].status == "END OF LIFE"
    assert by_name["org.hibernate:hibernate-validator"] == SbomRow(
        "Maven", "org.hibernate:hibernate-validator", "6.6.0", "pom.xml", "Hibernate ORM", "", "")


def test_sbom_exact_members_each_use_own_version():
    sbom = report(dependencies=[maven("org.springframework.boot:spring-boot-starter-web", "4.0.1"),
                                maven("org.springframework.boot:spring-boot", "3.2.0")]).sbom
    assert {s.name: s.status for s in sbom} == {
        "org.springframework.boot:spring-boot": "END OF LIFE",
        "org.springframework.boot:spring-boot-starter-web": "supported",
    }


def test_runtime_sbom_rows():
    assert report(findings=[finding("Java", "17", "17", POM)]).sbom == [
        SbomRow("Runtime", "Java", "17", "pom.xml", "Eclipse Temurin", "2027-10-31", "supported")]


def test_sbom_dedupes_on_ecosystem_name_source():
    sbom = report(dependencies=[Dependency("npm", "react", "17.0.2", "17.0.2", PKG),
                                Dependency("npm", "react", "17.0.2", "17.0.2", PKG)]).sbom
    assert sbom == [SbomRow("npm", "react", "17.0.2", "package.json", "React", "", "no EOL date")]


def test_sbom_merges_identical_os_readings():
    sbom = report(dependencies=[docker("node", "18-bullseye", "18"), docker("ruby", "3.3-bullseye", "3.3")]).sbom
    assert [s for s in sbom if s.name == "Debian"] == [
        SbomRow("Docker", "Debian", "11 (bullseye)", "Dockerfile", "Debian", "2024-08-14", "END OF LIFE")]


def test_sorting():
    rep = report(
        findings=[finding("Java", "17", "17", Path("b/pom.xml")), finding("Java", "17", "17", Path("a/pom.xml"))],
        dependencies=[maven("org.springframework.boot:spring-boot", "3.2.0", Path("a/pom.xml")),
                      maven("org.hibernate:hibernate-core", "5.6.15", Path("a/pom.xml"))],
    )
    assert [(r.found_in, r.component) for r in rep.rows] == [
        ("a/pom.xml", "Hibernate ORM"), ("a/pom.xml", "Java"), ("a/pom.xml", "Spring Boot"), ("b/pom.xml", "Java")]
    assert [(s.found_in, s.ecosystem, s.name) for s in rep.sbom] == [
        ("a/pom.xml", "Maven", "org.hibernate:hibernate-core"),
        ("a/pom.xml", "Maven", "org.springframework.boot:spring-boot"),
        ("a/pom.xml", "Runtime", "Java"),
        ("b/pom.xml", "Runtime", "Java"),
    ]


def test_detector_unrecognised_passed_through_and_deduped():
    gap = Unrecognised(POM, "couldn't read the Java version")
    rep = report(unrecognised=[gap, gap], dependencies=[
        maven("org.springframework.boot:spring-boot", None, missing="set by parent pom")])
    assert rep.unrecognised == [gap, Unrecognised(POM, "couldn't read the Spring Boot version (set by parent pom)")]
