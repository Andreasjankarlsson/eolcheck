from pathlib import Path

from eolchecker.api import Release
from eolchecker.models import finding
from eolchecker.rows import Row, build_rows


class FakeClient:
    def __init__(self, data):
        self.data = data
        self.calls = []

    def releases(self, product):
        self.calls.append(product)
        return self.data.get(product)


BOOT = [
    Release("4.1", "2026-05-20", False, "2027-07-31", "4.1.0"),
    Release("3.1", "2023-05-18", True, "2024-06-30", "3.1.12"),
]


def test_eol_row():
    rows = build_rows([finding("Spring Boot", "3.1.5", "3.1.5", Path("backend/pom.xml"))],
                      FakeClient({"spring-boot": BOOT}))
    assert rows == [Row("Spring Boot", "3.1.5", "backend/pom.xml", "2024-06-30", "4.1.0", "END OF LIFE")]


def test_major_only_cycle():
    data = {"dotnet": [Release("8", "2023-11-14", False, "2026-11-10", "8.0.21")]}
    [row] = build_rows([finding(".NET", "8.0", "net8.0", Path("api/Api.csproj"))], FakeClient(data))
    assert row.status == "supported"
    assert row.end_of_support == "2026-11-10"


def test_no_eol_date():
    data = {"react": [Release("19", "2024-12-05", False, None, "19.2.0"),
                      Release("17", "2020-10-20", False, None, "17.0.2")]}
    [row] = build_rows([finding("React", "17.0.2", "17.0.2", Path("package.json"))], FakeClient(data))
    assert (row.status, row.end_of_support, row.latest) == ("no EOL date", "—", "19.2.0")


def test_latest_drops_build_metadata():
    data = {"eclipse-temurin": [Release("27", "2026-09-15", False, "2027-03-23", "27.0.1.0.2+1"),
                                Release("17", "2021-09-14", False, "2029-09-30", "17.0.13+11")]}
    [row] = build_rows([finding("Java", "17", "17", Path("pom.xml"))], FakeClient(data))
    assert row.latest == "27.0.1"


def test_latest_keeps_normal_versions():
    data = {"dotnetfx": [Release("4.8.1", "2022-08-09", False, None, "4.8.1")]}
    [row] = build_rows([finding(".NET Framework", "4.8", "net48", Path("a.csproj"))], FakeClient(data))
    assert row.latest == "4.8.1"


def test_unknown_cycle():
    [row] = build_rows([finding("Spring Boot", "0.9", "0.9", Path("pom.xml"))], FakeClient({"spring-boot": BOOT}))
    assert (row.status, row.end_of_support) == ("unknown", "—")


def test_product_404():
    [row] = build_rows([finding("Spring Boot", "3.1.5", "3.1.5", Path("pom.xml"))], FakeClient({}))
    assert (row.status, row.latest) == ("unknown", "—")


def test_one_fetch_per_product():
    client = FakeClient({"angular": [Release("16", "2023-05-03", True, "2024-11-08", "16.2.12")]})
    build_rows([finding("Angular", "16.2.0", "16.2.0", Path("a/package.json")),
                finding("Angular", "16.1.0", "16.1.0", Path("b/package.json"))], client)
    assert client.calls == ["angular"]


def test_via_maven_suffix():
    [row] = build_rows([finding("Spring Boot", "3.1.5", "3.1.5", Path("api/pom.xml"), via_maven=True)],
                       FakeClient({"spring-boot": BOOT}))
    assert row.found_in == "api/pom.xml (via Maven)"


def test_sorted_by_file_then_component():
    data = {"spring-boot": BOOT, "eclipse-temurin": [Release("17", "2021-09-14", False, "2029-09-30", "17.0.13")]}
    rows = build_rows([
        finding("Java", "17", "17", Path("b/pom.xml")),
        finding("Java", "17", "17", Path("a/pom.xml")),
        finding("Spring Boot", "3.1.5", "3.1.5", Path("a/pom.xml")),
    ], FakeClient(data))
    assert [(r.found_in, r.component) for r in rows] == [
        ("a/pom.xml", "Spring Boot"), ("a/pom.xml", "Java"), ("b/pom.xml", "Java")]
