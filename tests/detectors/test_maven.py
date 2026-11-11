from pathlib import Path

import pytest

from eolchecker.detectors import DETECTORS, Context
from eolchecker.detectors.maven import MavenDetector, java_version, read_pom
from eolchecker.models import Finding, Unrecognised

NS = 'xmlns="http://maven.apache.org/POM/4.0.0"'


def pom(body: str, ns: bool = True) -> str:
    return f'<?xml version="1.0" encoding="UTF-8"?><project {NS if ns else ""}><modelVersion>4.0.0</modelVersion>{body}</project>'


BOOT_PARENT = ("<parent><groupId>org.springframework.boot</groupId>"
               "<artifactId>spring-boot-starter-parent</artifactId><version>3.1.5</version></parent>")


def dep(group, artifact, version=None, extra=""):
    v = f"<version>{version}</version>" if version else ""
    return f"<dependency><groupId>{group}</groupId><artifactId>{artifact}</artifactId>{v}{extra}</dependency>"


def run(root: Path, rel: str = "pom.xml", use_maven: bool = False):
    return MavenDetector().detect(root / rel, Context(root, use_maven=use_maven))


@pytest.mark.parametrize("raw,expected", [("1.8", "8"), ("17", "17"), ("21.0.1", "21"), ("${x}", None)])
def test_java_version(raw, expected):
    assert java_version(raw) == expected


def test_applies_to():
    assert MavenDetector().applies_to(Path("a/pom.xml"))
    assert not MavenDetector().applies_to(Path("a/build.xml"))


def test_spring_boot_parent(write_files):
    root = write_files({"backend/pom.xml": pom(BOOT_PARENT + "<properties><java.version>17</java.version></properties>")})
    assert run(root, "backend/pom.xml").findings == [
        Finding("Spring Boot", "spring-boot", "3.1.5", "3.1.5", Path("backend/pom.xml")),
        Finding("Java", "eclipse-temurin", "17", "17", Path("backend/pom.xml")),
    ]


def test_no_namespace_pom(write_files):
    root = write_files({"pom.xml": pom(BOOT_PARENT + "<properties><java.version>17</java.version></properties>", ns=False)})
    assert [f.component for f in run(root).findings] == ["Spring Boot", "Java"]


def test_boot_bom_import_with_property(write_files):
    body = ("<properties><spring-boot.version>3.2.4</spring-boot.version>"
            "<maven.compiler.release>21</maven.compiler.release></properties>"
            "<dependencyManagement><dependencies>"
            + dep("org.springframework.boot", "spring-boot-dependencies", "${spring-boot.version}",
                  "<type>pom</type><scope>import</scope>")
            + "</dependencies></dependencyManagement>")
    root = write_files({"pom.xml": pom(body)})
    found = {f.component: f.version for f in run(root).findings}
    assert found == {"Spring Boot": "3.2.4", "Java": "21"}


def test_java_from_compiler_plugin(write_files):
    body = ("<build><plugins><plugin><groupId>org.apache.maven.plugins</groupId>"
            "<artifactId>maven-compiler-plugin</artifactId><configuration><source>1.8</source>"
            "<target>1.8</target></configuration></plugin></plugins></build>")
    root = write_files({"pom.xml": pom(body)})
    assert run(root).findings == [Finding("Java", "eclipse-temurin", "8", "1.8", Path("pom.xml"))]


def test_explicit_libs(write_files):
    body = ("<properties><java.version>17</java.version></properties><dependencies>"
            + dep("org.hibernate.orm", "hibernate-core", "6.4.1.Final")
            + dep("org.apache.tomcat.embed", "tomcat-embed-core", "10.1.19")
            + dep("org.springframework", "spring-core", "6.1.5")
            + "</dependencies>")
    root = write_files({"pom.xml": pom(body)})
    found = {f.component: (f.version, f.display) for f in run(root).findings}
    assert found == {
        "Spring Framework": ("6.1.5", "6.1.5"),
        "Java": ("17", "17"),
        "Hibernate ORM": ("6.4.1", "6.4.1.Final"),
        "Apache Tomcat": ("10.1.19", "10.1.19"),
    }


def test_tomcat_version_property(write_files):
    body = BOOT_PARENT + "<properties><java.version>17</java.version><tomcat.version>10.1.30</tomcat.version></properties>"
    root = write_files({"pom.xml": pom(body)})
    assert "Apache Tomcat" in {f.component for f in run(root).findings}


def test_spring_framework_bom(write_files):
    body = ("<properties><java.version>17</java.version></properties><dependencyManagement><dependencies>"
            + dep("org.springframework", "spring-framework-bom", "5.3.39", "<type>pom</type><scope>import</scope>")
            + "</dependencies></dependencyManagement>")
    root = write_files({"pom.xml": pom(body)})
    assert ("Spring Framework", "5.3.39") in {(f.component, f.version) for f in run(root).findings}


def test_boot_managed_framework_not_reported(write_files):
    body = BOOT_PARENT + "<properties><java.version>17</java.version></properties><dependencies>" + \
        dep("org.springframework", "spring-core") + dep("org.springframework.boot", "spring-boot-starter-web") + \
        "</dependencies>"
    root = write_files({"pom.xml": pom(body)})
    assert [f.component for f in run(root).findings] == ["Spring Boot", "Java"]


def test_child_inherits_from_in_repo_parent(write_files):
    root_pom = pom(BOOT_PARENT + "<groupId>com.acme</groupId><artifactId>shop</artifactId><version>1.0</version>"
                   "<packaging>pom</packaging><properties><java.version>21</java.version></properties>")
    child = pom("<parent><groupId>com.acme</groupId><artifactId>shop</artifactId><version>1.0</version></parent>"
                "<artifactId>app</artifactId><dependencies>"
                + dep("org.springframework.boot", "spring-boot-starter-web") + "</dependencies>")
    root = write_files({"pom.xml": root_pom, "app/pom.xml": child})
    result = run(root, "app/pom.xml")
    # Covered by the parent's rows: no duplicate rows, and no gaps.
    assert (result.findings, result.unrecognised) == ([], [])
    assert [(f.component, f.version) for f in run(root).findings] == [("Spring Boot", "3.1.5"), ("Java", "21")]


def test_child_property_from_parent(write_files):
    root_pom = pom("<groupId>com.acme</groupId><artifactId>shop</artifactId><version>1.0</version>"
                   "<packaging>pom</packaging><properties><hibernate.version>6.2.0.Final</hibernate.version>"
                   "<java.version>17</java.version></properties>")
    child = pom("<parent><groupId>com.acme</groupId><artifactId>shop</artifactId><version>1.0</version></parent>"
                "<artifactId>app</artifactId><dependencies>"
                + dep("org.hibernate", "hibernate-core", "${hibernate.version}") + "</dependencies>")
    root = write_files({"pom.xml": root_pom, "app/pom.xml": child})
    result = run(root, "app/pom.xml")
    assert [(f.component, f.version) for f in result.findings] == [("Hibernate ORM", "6.2.0")]
    assert result.unrecognised == []


def test_company_parent_gap(write_files):
    body = ("<parent><groupId>com.acme</groupId><artifactId>acme-parent</artifactId><version>5</version></parent>"
            "<dependencies>" + dep("org.springframework.boot", "spring-boot-starter-web") + "</dependencies>")
    reading = read_pom(pom(body), Path("pom.xml"), {}, check_java=True)
    assert reading.has_gaps
    assert reading.gap_components == {"Spring Boot", "Java"}
    assert reading.result.unrecognised == [
        Unrecognised(Path("pom.xml"), "couldn't read the Spring Boot version"),
        Unrecognised(Path("pom.xml"), "couldn't read the Java version"),
    ]


def test_unresolved_property_gap(write_files):
    body = ("<properties><java.version>17</java.version></properties><dependencies>"
            + dep("org.hibernate.orm", "hibernate-core", "${hibernate.version}") + "</dependencies>")
    root = write_files({"pom.xml": pom(body)})
    assert run(root).unrecognised == [Unrecognised(Path("pom.xml"), "couldn't resolve ${hibernate.version}")]


def test_aggregator_pom_no_java_gap(write_files):
    root = write_files({"pom.xml": pom("<packaging>pom</packaging><modules><module>a</module></modules>")})
    result = run(root)
    assert (result.findings, result.unrecognised) == ([], [])


def test_broken_xml_unrecognised(write_files):
    root = write_files({"pom.xml": "<project><dependencies>"})
    assert run(root).unrecognised == [Unrecognised(Path("pom.xml"), "couldn't parse pom.xml")]


def test_registered():
    assert any(isinstance(d, MavenDetector) for d in DETECTORS)
