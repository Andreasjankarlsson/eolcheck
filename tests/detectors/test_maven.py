from pathlib import Path

import pytest

from eolchecker.detectors import DETECTORS, Context
from eolchecker.detectors.maven import INHERITABLE, MavenDetector, java_version, read_pom
from eolchecker.models import Dependency, Finding, Unrecognised

NS = 'xmlns="http://maven.apache.org/POM/4.0.0"'


def pom(body: str, ns: bool = True) -> str:
    return f'<?xml version="1.0" encoding="UTF-8"?><project {NS if ns else ""}><modelVersion>4.0.0</modelVersion>{body}</project>'


BOOT_PARENT = ("<parent><groupId>org.springframework.boot</groupId>"
               "<artifactId>spring-boot-starter-parent</artifactId><version>3.1.5</version></parent>")
BOOT_PARENT_NAME = "org.springframework.boot:spring-boot-starter-parent"


def dep(group, artifact, version=None, extra=""):
    v = f"<version>{version}</version>" if version else ""
    return f"<dependency><groupId>{group}</groupId><artifactId>{artifact}</artifactId>{v}{extra}</dependency>"


def run(root: Path, rel: str = "pom.xml", use_maven: bool = False):
    return MavenDetector().detect(root / rel, Context(root, use_maven=use_maven))


def names(result):
    return [d.name for d in result.dependencies]


@pytest.mark.parametrize("raw,expected", [("1.8", "8"), ("17", "17"), ("21.0.1", "21"), ("${x}", None)])
def test_java_version(raw, expected):
    assert java_version(raw) == expected


def test_applies_to():
    assert MavenDetector().applies_to(Path("a/pom.xml"))
    assert not MavenDetector().applies_to(Path("a/build.xml"))


def test_only_java_is_inherited():
    assert INHERITABLE == ("Java",)


def test_spring_boot_parent(write_files):
    root = write_files({"backend/pom.xml": pom(BOOT_PARENT + "<properties><java.version>17</java.version></properties>")})
    result = run(root, "backend/pom.xml")
    src = Path("backend/pom.xml")
    assert Dependency("Maven", BOOT_PARENT_NAME, "3.1.5", "3.1.5", src) in result.dependencies
    assert result.findings == [Finding("Java", "eclipse-temurin", "17", "17", src)]
    assert result.unrecognised == []


def test_no_namespace_pom(write_files):
    root = write_files({"pom.xml": pom(BOOT_PARENT + "<properties><java.version>17</java.version></properties>", ns=False)})
    result = run(root)
    assert names(result) == [BOOT_PARENT_NAME]
    assert [f.component for f in result.findings] == ["Java"]


def test_boot_bom_import_with_property(write_files):
    body = ("<properties><spring-boot.version>3.2.4</spring-boot.version>"
            "<maven.compiler.release>21</maven.compiler.release></properties>"
            "<dependencyManagement><dependencies>"
            + dep("org.springframework.boot", "spring-boot-dependencies", "${spring-boot.version}",
                  "<type>pom</type><scope>import</scope>")
            + "</dependencies></dependencyManagement>")
    root = write_files({"pom.xml": pom(body)})
    result = run(root)
    assert result.dependencies == [Dependency(
        "Maven", "org.springframework.boot:spring-boot-dependencies", "3.2.4", "3.2.4", Path("pom.xml"))]
    assert {f.component: f.version for f in result.findings} == {"Java": "21"}


def test_java_from_compiler_plugin(write_files):
    body = ("<build><plugins><plugin><groupId>org.apache.maven.plugins</groupId>"
            "<artifactId>maven-compiler-plugin</artifactId><configuration><source>1.8</source>"
            "<target>1.8</target></configuration></plugin></plugins></build>")
    root = write_files({"pom.xml": pom(body)})
    assert run(root).findings == [Finding("Java", "eclipse-temurin", "8", "1.8", Path("pom.xml"))]


def test_plugins_not_listed(write_files):
    body = ("<properties><java.version>17</java.version></properties>"
            "<build><plugins><plugin><groupId>org.apache.maven.plugins</groupId>"
            "<artifactId>maven-compiler-plugin</artifactId><version>3.11.0</version></plugin></plugins>"
            "<pluginManagement><plugins><plugin><groupId>org.apache.maven.plugins</groupId>"
            "<artifactId>maven-surefire-plugin</artifactId><version>3.2.5</version></plugin></plugins>"
            "</pluginManagement></build>")
    root = write_files({"pom.xml": pom(body)})
    assert run(root).dependencies == []


def test_explicit_libs(write_files):
    body = ("<properties><java.version>17</java.version></properties><dependencies>"
            + dep("org.hibernate.orm", "hibernate-core", "6.5.2.Final")
            + dep("org.apache.tomcat.embed", "tomcat-embed-core", "10.1.19")
            + dep("org.springframework", "spring-core", "6.1.5")
            + "</dependencies>")
    root = write_files({"pom.xml": pom(body)})
    result = run(root)
    src = Path("pom.xml")
    assert result.dependencies == [
        Dependency("Maven", "org.hibernate.orm:hibernate-core", "6.5.2", "6.5.2.Final", src),
        Dependency("Maven", "org.apache.tomcat.embed:tomcat-embed-core", "10.1.19", "10.1.19", src),
        Dependency("Maven", "org.springframework:spring-core", "6.1.5", "6.1.5", src),
    ]
    assert [f.component for f in result.findings] == ["Java"]


def test_versionless_dependency_kept_with_reason(write_files):
    body = BOOT_PARENT + "<properties><java.version>17</java.version></properties><dependencies>" + \
        dep("org.springframework.boot", "spring-boot-starter-web") + "</dependencies>"
    root = write_files({"pom.xml": pom(body)})
    result = run(root)
    src = Path("pom.xml")
    assert Dependency("Maven", "org.springframework.boot:spring-boot-starter-web", None, "set by parent pom", src,
                      missing="set by parent pom") in result.dependencies
    assert result.unrecognised == []


def test_own_dependency_management_sets_version(write_files):
    body = ("<properties><java.version>17</java.version></properties><dependencies>"
            + dep("org.hibernate.orm", "hibernate-core") + "</dependencies>"
            "<dependencyManagement><dependencies>" + dep("org.hibernate.orm", "hibernate-core", "6.4.1.Final")
            + "</dependencies></dependencyManagement>")
    reading = read_pom(pom(body), Path("pom.xml"), {}, check_java=True)
    assert reading.result.dependencies == [
        Dependency("Maven", "org.hibernate.orm:hibernate-core", "6.4.1", "6.4.1.Final", Path("pom.xml"))]
    assert not reading.has_gaps


def test_coordinates_resolve_properties(write_files):
    body = ("<properties><java.version>17</java.version><g>com.acme</g><a>lib</a></properties><dependencies>"
            + dep("${g}", "${a}", "1.2") + dep("${nope}", "other", "1.0") + "</dependencies>")
    root = write_files({"pom.xml": pom(body)})
    assert run(root).dependencies == [Dependency("Maven", "com.acme:lib", "1.2", "1.2", Path("pom.xml"))]


def test_child_inherits_from_in_repo_parent(write_files):
    root_pom = pom(BOOT_PARENT + "<groupId>com.acme</groupId><artifactId>shop</artifactId><version>1.0</version>"
                   "<packaging>pom</packaging><properties><java.version>21</java.version></properties>")
    child = pom("<parent><groupId>com.acme</groupId><artifactId>shop</artifactId><version>1.0</version></parent>"
                "<artifactId>app</artifactId><dependencies>"
                + dep("org.springframework.boot", "spring-boot-starter-web") + "</dependencies>")
    root = write_files({"pom.xml": root_pom, "app/pom.xml": child})
    result = run(root, "app/pom.xml")
    # Java is covered by the parent's row: no duplicate row, and no gap.
    assert (result.findings, result.unrecognised) == ([], [])
    assert names(result) == ["com.acme:shop", "org.springframework.boot:spring-boot-starter-web"]
    assert [(f.component, f.version) for f in run(root).findings] == [("Java", "21")]


def test_child_property_from_parent(write_files):
    root_pom = pom("<groupId>com.acme</groupId><artifactId>shop</artifactId><version>1.0</version>"
                   "<packaging>pom</packaging><properties><hibernate.version>6.2.0.Final</hibernate.version>"
                   "<java.version>17</java.version></properties>")
    child = pom("<parent><groupId>com.acme</groupId><artifactId>shop</artifactId><version>1.0</version></parent>"
                "<artifactId>app</artifactId><dependencies>"
                + dep("org.hibernate", "hibernate-core", "${hibernate.version}") + "</dependencies>")
    root = write_files({"pom.xml": root_pom, "app/pom.xml": child})
    result = run(root, "app/pom.xml")
    assert Dependency("Maven", "org.hibernate:hibernate-core", "6.2.0", "6.2.0.Final",
                      Path("app/pom.xml")) in result.dependencies
    assert result.findings == []
    assert result.unrecognised == []


def test_unresolved_property_gap(write_files):
    body = ("<properties><java.version>17</java.version></properties><dependencies>"
            + dep("org.hibernate.orm", "hibernate-core", "${hibernate.version}") + "</dependencies>")
    root = write_files({"pom.xml": pom(body)})
    result = run(root)
    assert result.dependencies == [Dependency(
        "Maven", "org.hibernate.orm:hibernate-core", None, "${hibernate.version}", Path("pom.xml"),
        missing="couldn't resolve ${hibernate.version}")]
    assert result.unrecognised == []


def test_aggregator_pom_no_java_gap(write_files):
    root = write_files({"pom.xml": pom("<packaging>pom</packaging><modules><module>a</module></modules>")})
    result = run(root)
    assert (result.findings, result.unrecognised) == ([], [])


def test_latin1_pom(tmp_path):
    xml = ('<?xml version="1.0" encoding="ISO-8859-1"?><project><name>José</name>' + BOOT_PARENT
           + "<properties><java.version>11</java.version></properties></project>")
    (tmp_path / "pom.xml").write_bytes(xml.encode("iso-8859-1"))
    result = run(tmp_path)
    assert names(result) == [BOOT_PARENT_NAME]
    assert [(f.component, f.version) for f in result.findings] == [("Java", "11")]


def test_broken_xml_unrecognised(write_files):
    root = write_files({"pom.xml": "<project><dependencies>"})
    assert run(root).unrecognised == [Unrecognised(Path("pom.xml"), "couldn't parse pom.xml")]


def test_registered():
    assert any(isinstance(d, MavenDetector) for d in DETECTORS)
