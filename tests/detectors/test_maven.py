from pathlib import Path

import pytest

from eolchecker.detectors import DETECTORS, Context
from eolchecker.detectors.maven import MavenDetector, java_version, read_pom
from eolchecker.models import Dependency, Finding, Unrecognised
from eolchecker.rows import build_rows

from ..fakes import index, product
from ..fakes import rel as release

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
        Finding("Spring Boot", "spring-boot", "3.1.5", "3.1.5", Path("backend/pom.xml"),
                origin="spring-boot-starter-parent (parent)"),
        Finding("Java", "eclipse-temurin", "17", "17", Path("backend/pom.xml"), origin="java.version"),
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
    assert run(root).findings == [Finding("Java", "eclipse-temurin", "8", "1.8", Path("pom.xml"),
                                          origin="maven-compiler-plugin")]


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


def test_starter_alone_does_not_report_framework_libs(write_files):
    body = BOOT_PARENT + "<properties><java.version>17</java.version></properties><dependencies>" + \
        dep("org.springframework.boot", "spring-boot-starter-web") + "</dependencies>"
    root = write_files({"pom.xml": pom(body)})
    result = run(root)
    assert [f.component for f in result.findings] == ["Spring Boot", "Java"]
    assert result.unrecognised == []


@pytest.mark.parametrize("group,artifact,component", [
    ("org.springframework", "spring-context", "Spring Framework"),
    ("org.hibernate.orm", "hibernate-core", "Hibernate ORM"),
    ("org.apache.tomcat.embed", "tomcat-embed-core", "Apache Tomcat"),
])
def test_versionless_declaration_is_a_gap(write_files, group, artifact, component):
    body = BOOT_PARENT + "<properties><java.version>17</java.version></properties><dependencies>" + \
        dep(group, artifact) + "</dependencies>"
    reading = read_pom(pom(body), Path("pom.xml"), {}, check_java=True)
    assert [f.component for f in reading.result.findings] == ["Spring Boot", "Java"]
    assert reading.gap_components == {component}
    assert reading.result.unrecognised == [Unrecognised(Path("pom.xml"), f"{component} version is set by Spring Boot")]


def test_versionless_declaration_with_company_parent(write_files):
    body = ("<parent><groupId>com.acme</groupId><artifactId>acme-parent</artifactId><version>5</version></parent>"
            "<properties><java.version>17</java.version></properties><dependencies>"
            + dep("org.hibernate.orm", "hibernate-core") + "</dependencies>")
    reading = read_pom(pom(body), Path("pom.xml"), {}, check_java=True)
    assert reading.result.unrecognised == [
        Unrecognised(Path("pom.xml"), "Hibernate ORM version is set by a parent pom or BOM")]


def test_versionless_declaration_reported_once_at_in_repo_parent(write_files):
    root_pom = pom(BOOT_PARENT + "<groupId>com.acme</groupId><artifactId>shop</artifactId><version>1.0</version>"
                   "<packaging>pom</packaging><properties><java.version>21</java.version></properties>"
                   "<dependencies>" + dep("org.hibernate.orm", "hibernate-core") + "</dependencies>")
    child = pom("<parent><groupId>com.acme</groupId><artifactId>shop</artifactId><version>1.0</version></parent>"
                "<artifactId>app</artifactId>")
    root = write_files({"pom.xml": root_pom, "app/pom.xml": child})
    assert run(root, "app/pom.xml").unrecognised == []
    assert [u.reason for u in run(root).unrecognised] == ["Hibernate ORM version is set by Spring Boot"]


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


def test_latin1_pom(tmp_path):
    xml = ('<?xml version="1.0" encoding="ISO-8859-1"?><project><name>José</name>' + BOOT_PARENT
           + "<properties><java.version>11</java.version></properties></project>")
    (tmp_path / "pom.xml").write_bytes(xml.encode("iso-8859-1"))
    assert [(f.component, f.version) for f in run(tmp_path).findings] == [("Spring Boot", "3.1.5"), ("Java", "11")]


def test_broken_xml_unrecognised(write_files):
    root = write_files({"pom.xml": "<project><dependencies>"})
    assert run(root).unrecognised == [Unrecognised(Path("pom.xml"), "couldn't parse pom.xml")]


def test_registered():
    assert any(isinstance(d, MavenDetector) for d in DETECTORS)


BOOT = product("spring-boot", "Spring Boot", ["pkg:maven/org.springframework.boot/spring-boot-starter-web"])
JACKSON = product("jackson-databind", "Jackson Databind", ["pkg:maven/com.fasterxml.jackson.core/jackson-databind"])
JACKSON_KEY = "maven:com.fasterxml.jackson.core/jackson-databind"
JAVA17 = "<properties><java.version>17</java.version></properties>"
COMPANY_PARENT = "<parent><groupId>com.acme</groupId><artifactId>acme-parent</artifactId><version>5</version></parent>"


def run_idx(root, rel="pom.xml", *products, use_maven=False):
    return MavenDetector().detect(root / rel, Context(root, use_maven=use_maven, index=index(*products)))


def must_not_run(cmd, cwd):
    raise AssertionError("Maven should not run")


def plugin(group, artifact, version):
    g = f"<groupId>{group}</groupId>" if group else ""
    return f"<plugin>{g}<artifactId>{artifact}</artifactId><version>{version}</version></plugin>"


def test_every_dependency_and_plugin_is_reported(write_files):
    body = (JAVA17 + "<dependencies>"
            + dep("org.projectlombok", "lombok", "1.18.30", "<scope>provided</scope>")
            + dep("org.junit.jupiter", "junit-jupiter", "5.10.0", "<scope>test</scope>")
            + "</dependencies><build><plugins>"
            + plugin("org.jacoco", "jacoco-maven-plugin", "0.8.11")
            + plugin(None, "maven-surefire-plugin", "3.2.5")
            + "</plugins></build>")
    result = run_idx(write_files({"pom.xml": pom(body)}))
    src = Path("pom.xml")
    assert result.dependencies == [
        Dependency("maven:org.projectlombok/lombok", "lombok", "1.18.30", "1.18.30", src),
        Dependency("maven:org.junit.jupiter/junit-jupiter", "junit-jupiter", "5.10.0", "5.10.0", src),
        Dependency("maven:org.jacoco/jacoco-maven-plugin", "jacoco-maven-plugin", "0.8.11", "0.8.11", src),
        Dependency("maven:org.apache.maven.plugins/maven-surefire-plugin", "maven-surefire-plugin",
                   "3.2.5", "3.2.5", src),
    ]
    assert result.unrecognised == []


def test_version_from_own_dependency_management(write_files):
    body = ("<properties><java.version>17</java.version><jackson.version>2.15.2</jackson.version></properties>"
            "<dependencyManagement><dependencies>"
            + dep("com.fasterxml.jackson.core", "jackson-databind", "${jackson.version}")
            + "</dependencies></dependencyManagement><dependencies>"
            + dep("com.fasterxml.jackson.core", "jackson-databind") + "</dependencies>")
    result = run_idx(write_files({"pom.xml": pom(body)}), "pom.xml", JACKSON)
    assert result.dependencies == [Dependency(JACKSON_KEY, "jackson-databind", "2.15.2", "2.15.2", Path("pom.xml"))]
    assert result.unrecognised == []


def test_version_from_plugin_management(write_files):
    body = (JAVA17 + "<build><pluginManagement><plugins>" + plugin(None, "maven-surefire-plugin", "3.2.5")
            + "</plugins></pluginManagement><plugins><plugin><artifactId>maven-surefire-plugin</artifactId>"
            "</plugin></plugins></build>")
    [d] = run_idx(write_files({"pom.xml": pom(body)})).dependencies
    assert (d.key, d.version) == ("maven:org.apache.maven.plugins/maven-surefire-plugin", "3.2.5")


def test_managed_entries_alone_are_not_dependencies(write_files):
    body = (JAVA17 + "<dependencyManagement><dependencies>"
            + dep("com.fasterxml.jackson.core", "jackson-databind", "2.15.2")
            + "</dependencies></dependencyManagement>")
    result = run_idx(write_files({"pom.xml": pom(body)}), "pom.xml", JACKSON)
    assert (result.dependencies, result.unrecognised) == ([], [])


def test_starters_join_boot_row_without_gap(write_files):
    body = BOOT_PARENT + "<properties><java.version>17</java.version></properties><dependencies>" + \
        dep("org.springframework.boot", "spring-boot-starter-web") + "</dependencies>"
    result = run_idx(write_files({"pom.xml": pom(body)}), "pom.xml", BOOT)
    assert result.unrecognised == []
    assert [(d.name, d.version) for d in result.dependencies] == [("spring-boot-starter-web", None)]


def test_tracked_versionless_is_a_gap(write_files):
    body = BOOT_PARENT + JAVA17 + "<dependencies>" + dep("com.fasterxml.jackson.core", "jackson-databind") \
        + dep("com.fasterxml.jackson.core", "jackson-databind", extra="<classifier>x</classifier>") \
        + "</dependencies>"
    result = run_idx(write_files({"pom.xml": pom(body)}), "pom.xml", BOOT, JACKSON)
    assert result.unrecognised == [Unrecognised(Path("pom.xml"), "Jackson Databind version is set by Spring Boot")]
    assert [(d.name, d.version) for d in result.dependencies] == [("jackson-databind", None)] * 2


def test_tracked_versionless_under_company_parent(write_files):
    body = COMPANY_PARENT + JAVA17 + "<dependencies>" + dep("com.fasterxml.jackson.core", "jackson-databind") \
        + "</dependencies>"
    reading = read_pom(pom(body), Path("pom.xml"), {}, check_java=True, index=index(JACKSON))
    assert reading.result.unrecognised == [
        Unrecognised(Path("pom.xml"), "Jackson Databind version is set by a parent pom or BOM")]
    assert reading.gap_components == {"Jackson Databind"}
    assert reading.gaps[0][0] == JACKSON_KEY


def test_tracked_unresolved_property_is_a_gap(write_files):
    body = JAVA17 + "<dependencies>" + dep("com.fasterxml.jackson.core", "jackson-databind", "${jackson.version}") \
        + "</dependencies>"
    result = run_idx(write_files({"pom.xml": pom(body)}), "pom.xml", JACKSON)
    assert result.unrecognised == [Unrecognised(Path("pom.xml"), "couldn't resolve ${jackson.version}")]


def test_untracked_versionless_is_silent(write_files):
    body = JAVA17 + "<dependencies>" + dep("org.projectlombok", "lombok") + "</dependencies>"
    result = run_idx(write_files({"pom.xml": pom(body)}), "pom.xml", JACKSON)
    assert result.unrecognised == []
    assert result.dependencies == [Dependency("maven:org.projectlombok/lombok", "lombok", None, None, Path("pom.xml"))]


def test_child_covered_by_parent_product_has_no_row(write_files):
    root_pom = pom(BOOT_PARENT + "<groupId>com.acme</groupId><artifactId>shop</artifactId><version>1.0</version>"
                   "<packaging>pom</packaging><properties><java.version>21</java.version></properties>")
    child = pom("<parent><groupId>com.acme</groupId><artifactId>shop</artifactId><version>1.0</version></parent>"
                "<artifactId>app</artifactId><dependencies>"
                + dep("org.springframework.boot", "spring-boot-starter-web") + "</dependencies>")
    root = write_files({"pom.xml": root_pom, "app/pom.xml": child})
    det = MavenDetector(runner=must_not_run)
    result = det.detect(root / "app/pom.xml", Context(root, use_maven=True, index=index(BOOT)))
    assert (result.findings, result.unrecognised, result.dependencies) == ([], [], [])


def test_child_gets_version_from_parent_dependency_management(write_files):
    root_pom = pom("<groupId>com.acme</groupId><artifactId>shop</artifactId><version>1.0</version>"
                   "<packaging>pom</packaging><properties><java.version>17</java.version></properties>"
                   "<dependencyManagement><dependencies>"
                   + dep("com.fasterxml.jackson.core", "jackson-databind", "2.15.2")
                   + dep("org.hibernate.orm", "hibernate-core", "6.4.4.Final")
                   + "</dependencies></dependencyManagement>")
    child = pom("<parent><groupId>com.acme</groupId><artifactId>shop</artifactId><version>1.0</version></parent>"
                "<artifactId>app</artifactId><dependencies>"
                + dep("com.fasterxml.jackson.core", "jackson-databind")
                + dep("org.hibernate.orm", "hibernate-core") + "</dependencies>")
    root = write_files({"pom.xml": root_pom, "app/pom.xml": child})
    det = MavenDetector(runner=must_not_run)
    result = det.detect(root / "app/pom.xml", Context(root, use_maven=True, index=index(JACKSON)))
    src = Path("app/pom.xml")
    assert result.unrecognised == []
    assert result.findings == [Finding("Hibernate ORM", "hibernate-orm", "6.4.4", "6.4.4.Final", src,
                                       origin="hibernate-core")]
    assert result.dependencies[0] == Dependency(JACKSON_KEY, "jackson-databind", "2.15.2", "2.15.2", src)


HIBERNATE = product("hibernate-orm", "Hibernate ORM", ["pkg:maven/org.hibernate.orm/hibernate-core",
                                                       "pkg:maven/org.hibernate.orm/hibernate-envers"])


def test_special_product_not_matched_by_special_case_is_a_gap(write_files):
    body = BOOT_PARENT + JAVA17 + "<dependencies>" + dep("org.hibernate.orm", "hibernate-envers") + "</dependencies>"
    result = run_idx(write_files({"pom.xml": pom(body)}), "pom.xml", HIBERNATE)
    assert result.unrecognised == [Unrecognised(Path("pom.xml"), "Hibernate ORM version is set by Spring Boot")]


def test_special_case_gap_not_repeated_for_sibling(write_files):
    body = BOOT_PARENT + JAVA17 + "<dependencies>" + dep("org.hibernate.orm", "hibernate-core") \
        + dep("org.hibernate.orm", "hibernate-envers") + "</dependencies>"
    result = run_idx(write_files({"pom.xml": pom(body)}), "pom.xml", HIBERNATE)
    assert result.unrecognised == [Unrecognised(Path("pom.xml"), "Hibernate ORM version is set by Spring Boot")]


def test_parent_managed_version_uses_child_property(write_files):
    root_pom = pom("<groupId>com.acme</groupId><artifactId>shop</artifactId><version>1.0</version>"
                   "<packaging>pom</packaging><properties><java.version>17</java.version>"
                   "<hibernate.version>6.2.0.Final</hibernate.version></properties>"
                   "<dependencyManagement><dependencies>"
                   + dep("org.hibernate.orm", "hibernate-core", "${hibernate.version}")
                   + "</dependencies></dependencyManagement>")
    child = pom("<parent><groupId>com.acme</groupId><artifactId>shop</artifactId><version>1.0</version></parent>"
                "<artifactId>app</artifactId><properties><hibernate.version>6.4.4.Final</hibernate.version>"
                "</properties><dependencies>" + dep("org.hibernate.orm", "hibernate-core") + "</dependencies>")
    root = write_files({"pom.xml": root_pom, "app/pom.xml": child})
    det = MavenDetector(runner=must_not_run)
    result = det.detect(root / "app/pom.xml", Context(root, use_maven=True, index=index(HIBERNATE)))
    assert [(f.component, f.version) for f in result.findings] == [("Hibernate ORM", "6.4.4")]
    assert [d.version for d in result.dependencies] == ["6.4.4"]
    assert result.unrecognised == []


def test_origins(write_files):
    body = BOOT_PARENT + JAVA17
    found = {f.component: f.origin for f in run_idx(write_files({"pom.xml": pom(body)})).findings}
    assert found == {"Spring Boot": "spring-boot-starter-parent (parent)", "Java": "java.version"}


def test_origins_from_boms_and_properties(write_files):
    body = ("<properties><maven.compiler.release>21</maven.compiler.release>"
            "<tomcat.version>10.1.30</tomcat.version></properties><dependencyManagement><dependencies>"
            + dep("org.springframework.boot", "spring-boot-dependencies", "3.2.4", "<type>pom</type><scope>import</scope>")
            + dep("org.springframework", "spring-framework-bom", "6.1.5", "<type>pom</type><scope>import</scope>")
            + "</dependencies></dependencyManagement><dependencies>"
            + dep("org.hibernate.orm", "hibernate-core", "6.4.1.Final") + "</dependencies>")
    found = {f.component: f.origin for f in run_idx(write_files({"pom.xml": pom(body)})).findings}
    assert found == {"Spring Boot": "spring-boot-dependencies", "Spring Framework": "spring-framework-bom",
                     "Java": "maven.compiler.release", "Hibernate ORM": "hibernate-core",
                     "Apache Tomcat": "tomcat.version"}


CLOUD = product("spring-cloud", "Spring Cloud", ["pkg:maven/org.springframework.cloud/spring-cloud-dependencies"])
CLOUD_KEY = "maven:org.springframework.cloud/spring-cloud-dependencies"


def test_tracked_bom_import_is_a_dependency(write_files):
    body = (JAVA17 + "<properties><cloud.version>2023.0.0</cloud.version></properties><dependencyManagement><dependencies>"
            + dep("org.springframework.cloud", "spring-cloud-dependencies", "${cloud.version}",
                  "<type>pom</type><scope>import</scope>")
            + dep("com.fasterxml.jackson", "jackson-bom", "2.15.2", "<type>pom</type><scope>import</scope>")
            + "</dependencies></dependencyManagement>")
    result = run_idx(write_files({"pom.xml": pom(body)}), "pom.xml", CLOUD)
    assert result.dependencies == [Dependency(CLOUD_KEY, "spring-cloud-dependencies", "2023.0.0", "2023.0.0",
                                              Path("pom.xml"))]
    assert result.unrecognised == []


def test_unresolvable_bom_import_is_skipped(write_files):
    body = (JAVA17 + "<dependencyManagement><dependencies>"
            + dep("org.springframework.cloud", "spring-cloud-dependencies", "${cloud.version}",
                  "<type>pom</type><scope>import</scope>")
            + "</dependencies></dependencyManagement>")
    result = run_idx(write_files({"pom.xml": pom(body)}), "pom.xml", CLOUD)
    assert (result.dependencies, result.unrecognised) == ([], [])


def test_boot_bom_import_joins_the_boot_row_once(write_files):
    boot = product("spring-boot", "Spring Boot", ["pkg:maven/org.springframework.boot/spring-boot-dependencies"],
                   [release("3.2", "2023-11-23", True, "2024-11-23", "3.2.12")])
    body = (JAVA17 + "<dependencyManagement><dependencies>"
            + dep("org.springframework.boot", "spring-boot-dependencies", "3.2.4", "<type>pom</type><scope>import</scope>")
            + "</dependencies></dependencyManagement>")
    idx = index(boot)
    root = write_files({"pom.xml": pom(body)})
    result = MavenDetector().detect(root / "pom.xml", Context(root, use_maven=False, index=idx))
    assert [d.name for d in result.dependencies] == ["spring-boot-dependencies"]
    boot_rows = [r for r in build_rows(result.findings, result.dependencies, idx) if r.component == "Spring Boot"]
    assert [(r.dependencies, r.version) for r in boot_rows] == [(("spring-boot-dependencies",), "3.2.4")]


def test_bom_import_is_not_a_managed_version(write_files):
    body = (JAVA17 + "<dependencyManagement><dependencies>"
            + dep("com.fasterxml.jackson", "jackson-bom", "2.15.2", "<type>pom</type><scope>import</scope>")
            + "</dependencies></dependencyManagement><dependencies>"
            + dep("com.fasterxml.jackson", "jackson-bom") + "</dependencies>")
    [d] = run_idx(write_files({"pom.xml": pom(body)})).dependencies
    assert d.version is None
