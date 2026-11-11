from pathlib import Path

from eolchecker.catalog import PurlIndex
from eolchecker.models import Dependency, finding
from eolchecker.rows import Row, build_rows, untracked_by_file
from .fakes import index, product, rel

BOOT = product(
    "spring-boot", "Spring Boot",
    ["pkg:maven/org.springframework.boot/spring-boot-starter-web",
     "pkg:maven/org.springframework.boot/spring-boot-starter-test"],
    [rel("3.4", "2024-11-21", False, "2025-12-31", "3.4.1"),
     rel("3.2", "2023-11-23", True, "2024-11-23", "3.2.12"),
     rel("4.1", "2026-06-30", False, "2027-07-31", "4.1.2")])
WEB = "maven:org.springframework.boot/spring-boot-starter-web"
TEST = "maven:org.springframework.boot/spring-boot-starter-test"
POM = Path("backend/pom.xml")


def dep(key, name, version, source=POM, via_maven=False):
    return Dependency(key, name, version, version, source, via_maven)


def test_one_row_per_product_lowest_version_wins():
    deps = [dep(WEB, "spring-boot-starter-web", "3.2.0"), dep(TEST, "spring-boot-starter-test", "3.4.1")]
    assert build_rows([], deps, index(BOOT)) == [
        Row("Spring Boot", ("spring-boot-starter-test", "spring-boot-starter-web"),
            "3.2.0 (also 3.4.1)", "backend/pom.xml", "2024-11-23", "4.1.2", "END OF LIFE")]


def test_same_versions_show_once():
    deps = [dep(WEB, "spring-boot-starter-web", "3.4.1"), dep(TEST, "spring-boot-starter-test", "3.4.1")]
    [row] = build_rows([], deps, index(BOOT))
    assert row.version == "3.4.1"
    assert row.status == "supported"


def test_versionless_dependency_joins_row():
    deps = [dep(WEB, "spring-boot-starter-web", None)]
    f = finding("Spring Boot", "3.4.1", "3.4.1", POM, origin="spring-boot-starter-parent (parent)")
    [row] = build_rows([f], deps, index(BOOT))
    assert row.dependencies == ("spring-boot-starter-parent (parent)", "spring-boot-starter-web")
    assert row.version == "3.4.1"


def test_versionless_group_without_version_is_dropped():
    assert build_rows([], [dep(WEB, "spring-boot-starter-web", None)], index(BOOT)) == []


def test_same_package_twice_listed_once():
    deps = [dep(WEB, "spring-boot-starter-web", "3.4.1"), dep(WEB, "spring-boot-starter-web", "3.4.1")]
    [row] = build_rows([], deps, index(BOOT))
    assert row.dependencies == ("spring-boot-starter-web",)


def test_runtime_findings_stay_one_row_each():
    dotnet = product("dotnet", ".NET", [], [rel("8", "2023-11-14", False, "2026-11-10", "8.0.21"),
                                           rel("6", "2021-11-08", True, "2024-11-12", "6.0.36")])
    csproj = Path("api/Api.csproj")
    rows = build_rows([finding(".NET", "6.0", "net6.0", csproj), finding(".NET", "8.0", "net8.0", csproj)],
                      [], index(dotnet))
    assert [(r.version, r.status) for r in rows] == [("net6.0", "END OF LIFE"), ("net8.0", "supported")]
    assert all(r.dependencies == () for r in rows)


def test_runtime_merges_with_matching_package_group():
    dotnet = product("dotnet", ".NET", ["pkg:nuget/Microsoft.AspNetCore.App"],
                     [rel("8", "2023-11-14", False, "2026-11-10", "8.0.21")])
    csproj = Path("api/Api.csproj")
    deps = [dep("nuget:microsoft.aspnetcore.app", "Microsoft.AspNetCore.App", "8.0.1", csproj)]
    rows = build_rows([finding(".NET", "8.0", "net8.0", csproj)], deps, index(dotnet))
    assert len(rows) == 1
    assert rows[0].version == "net8.0 (also 8.0.1)"
    assert rows[0].dependencies == ("Microsoft.AspNetCore.App",)


def test_two_products_for_one_dependency_give_two_rows():
    other = product("other", "Other", ["pkg:maven/org.springframework.boot/spring-boot-starter-web"],
                    [rel("3", "2024-01-01", False, "2030-01-01", "3.0")])
    rows = build_rows([], [dep(WEB, "spring-boot-starter-web", "3.4.1")], index(BOOT, other))
    assert sorted(r.component for r in rows) == ["Other", "Spring Boot"]


def test_unknown_cycle_is_unknown_version():
    [row] = build_rows([finding("Spring Boot", "0.9", "0.9", POM)], [], index(BOOT))
    assert (row.status, row.end_of_support) == ("unknown version", "—")


def test_override_product_missing_from_catalogue_is_not_tracked():
    [row] = build_rows([finding("React", "17.0.2", "17.0.2", Path("package.json"))], [], PurlIndex())
    assert (row.status, row.latest) == ("not tracked", "—")


def test_major_only_cycle():
    dotnet = product("dotnet", ".NET", [], [rel("8", "2023-11-14", False, "2026-11-10", "8.0.21")])
    [row] = build_rows([finding(".NET", "8.0", "net8.0", Path("api/Api.csproj"))], [], index(dotnet))
    assert (row.status, row.end_of_support) == ("supported", "2026-11-10")


def test_no_eol_date():
    react = product("react", "React", [], [rel("19", "2024-12-05", False, None, "19.2.0"),
                                           rel("17", "2020-10-20", False, None, "17.0.2")])
    [row] = build_rows([finding("React", "17.0.2", "17.0.2", Path("package.json"))], [], index(react))
    assert (row.status, row.end_of_support, row.latest) == ("no EOL date", "—", "19.2.0")


def test_latest_drops_build_metadata():
    java = product("eclipse-temurin", "Java", [], [rel("27", "2026-09-15", False, "2027-03-23", "27.0.1.0.2+1"),
                                                   rel("17", "2021-09-14", False, "2029-09-30", "17.0.13+11")])
    [row] = build_rows([finding("Java", "17", "17", Path("pom.xml"))], [], index(java))
    assert row.latest == "27.0.1"


def test_latest_keeps_normal_versions():
    fx = product("dotnetfx", ".NET Framework", [], [rel("4.8.1", "2022-08-09", False, None, "4.8.1")])
    [row] = build_rows([finding(".NET Framework", "4.8", "net48", Path("a.csproj"))], [], index(fx))
    assert row.latest == "4.8.1"


def test_via_maven_suffix():
    [row] = build_rows([finding("Spring Boot", "3.2.5", "3.2.5", Path("api/pom.xml"), via_maven=True)],
                       [], index(BOOT))
    assert row.found_in == "api/pom.xml (via Maven)"


def test_via_maven_suffix_from_dependency():
    [row] = build_rows([], [dep(WEB, "spring-boot-starter-web", "3.4.1", via_maven=True)], index(BOOT))
    assert row.found_in == "backend/pom.xml (via Maven)"


def test_untracked_by_file():
    deps = [dep("maven:org.projectlombok/lombok", "lombok", "1.18.30"),
            dep("maven:org.projectlombok/lombok", "lombok", None),
            dep(WEB, "spring-boot-starter-web", "3.4.1")]
    assert untracked_by_file(deps, index(BOOT)) == {POM: ["lombok"]}


def test_sorted_by_file_then_component_order_then_label():
    java = product("eclipse-temurin", "Java", [], [rel("17", "2021-09-14", False, "2029-09-30", "17.0.13")])
    zed = product("zed", "Zed", ["pkg:npm/zed"], [rel("1", "2020-01-01", False, "2030-01-01", "1.0")])
    abc = product("abc", "Abc", ["pkg:npm/abc"], [rel("1", "2020-01-01", False, "2030-01-01", "1.0")])
    a, b = Path("a/pom.xml"), Path("b/pom.xml")
    rows = build_rows(
        [finding("Java", "17", "17", b), finding("Java", "17", "17", a),
         finding("Spring Boot", "3.4.1", "3.4.1", a)],
        [dep("npm:zed", "zed", "1.0", a), dep("npm:abc", "abc", "1.0", a)],
        index(BOOT, java, zed, abc))
    assert [(r.found_in, r.component) for r in rows] == [
        ("a/pom.xml", "Spring Boot"), ("a/pom.xml", "Java"), ("a/pom.xml", "Abc"),
        ("a/pom.xml", "Zed"), ("b/pom.xml", "Java")]
