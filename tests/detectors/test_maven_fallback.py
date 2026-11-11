import os
import subprocess
from pathlib import Path

from eolchecker.detectors import Context
from eolchecker.detectors import maven_fallback
from eolchecker.detectors.maven import MavenDetector
from eolchecker.models import Dependency, Finding, Unrecognised

from ..fakes import index, product

COMPANY_POM = """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <parent><groupId>com.acme</groupId><artifactId>acme-parent</artifactId><version>5</version></parent>
  <artifactId>api</artifactId>
  <dependencies>
    <dependency><groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter-web</artifactId></dependency>
  </dependencies>
</project>"""

EFFECTIVE = """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <artifactId>api</artifactId>
  <properties><maven.compiler.release>17</maven.compiler.release></properties>
  <dependencies>
    <dependency><groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter-web</artifactId><version>3.3.2</version></dependency>
    <dependency><groupId>org.hibernate.orm</groupId><artifactId>hibernate-core</artifactId><version>6.5.2.Final</version></dependency>
  </dependencies>
</project>"""

COMPLETE_POM = """<project><parent><groupId>org.springframework.boot</groupId>
<artifactId>spring-boot-starter-parent</artifactId><version>3.3.2</version></parent>
<properties><java.version>17</java.version></properties></project>"""


class FakeRunner:
    def __init__(self, output=EFFECTIVE, returncode=0):
        self.output = output
        self.returncode = returncode
        self.calls = []

    def __call__(self, cmd, cwd):
        self.calls.append(cmd)
        out = next(a for a in cmd if a.startswith("-Doutput="))[len("-Doutput="):]
        if self.returncode == 0:
            Path(out).write_text(self.output, encoding="utf-8")
        return subprocess.CompletedProcess(cmd, self.returncode, "", "")


def detect(root, runner, rel="api/pom.xml", use_maven=True):
    det = MavenDetector(runner=runner, tmp_dir=root)
    return det.detect(root / rel, Context(root, use_maven=use_maven))


def with_mvn(monkeypatch):
    monkeypatch.setattr(maven_fallback.shutil, "which", lambda name: "/usr/bin/mvn")


def test_fallback_fills_gaps(write_files, monkeypatch):
    with_mvn(monkeypatch)
    root = write_files({"api/pom.xml": COMPANY_POM})
    result = detect(root, FakeRunner())
    assert result.findings == [
        Finding("Spring Boot", "spring-boot", "3.3.2", "3.3.2", Path("api/pom.xml"), via_maven=True,
                origin="spring-boot-starter-web"),
        Finding("Java", "eclipse-temurin", "17", "17", Path("api/pom.xml"), via_maven=True,
                origin="maven.compiler.release"),
    ]
    assert result.unrecognised == []


def test_prints_progress_while_maven_runs(write_files, monkeypatch, capsys):
    with_mvn(monkeypatch)
    root = write_files({"api/pom.xml": COMPANY_POM})
    detect(root, FakeRunner())
    assert "Asking Maven about api/pom.xml" in capsys.readouterr().err


def test_no_maven_flag_skips(write_files, monkeypatch):
    with_mvn(monkeypatch)
    root = write_files({"api/pom.xml": COMPANY_POM})
    runner = FakeRunner()
    result = detect(root, runner, use_maven=False)
    assert runner.calls == []
    assert len(result.unrecognised) == 2


def test_fallback_failure_keeps_gap(write_files, monkeypatch):
    with_mvn(monkeypatch)
    root = write_files({"api/pom.xml": COMPANY_POM})
    result = detect(root, FakeRunner(returncode=1))
    assert Unrecognised(Path("api/pom.xml"), "couldn't read the Spring Boot version (Maven fallback failed)") \
        in result.unrecognised


def test_maven_not_found(write_files, monkeypatch):
    monkeypatch.setattr(maven_fallback.shutil, "which", lambda name: None)
    root = write_files({"api/pom.xml": COMPANY_POM})
    runner = FakeRunner()
    result = detect(root, runner)
    assert runner.calls == []
    assert Unrecognised(Path("api/pom.xml"), "couldn't read the Java version (Maven not found)") in result.unrecognised


def test_prefers_mvnw(write_files, monkeypatch):
    with_mvn(monkeypatch)
    root = write_files({"api/pom.xml": COMPANY_POM, "mvnw": "#!/bin/sh\n"})
    os.chmod(root / "mvnw", 0o755)
    runner = FakeRunner()
    detect(root, runner)
    assert runner.calls[0][0] == str(root / "mvnw")
    assert "help:effective-pom" in runner.calls[0]
    assert "-N" in runner.calls[0]


def test_windows_finds_mvnw_cmd_without_exec_bit(write_files, monkeypatch):
    monkeypatch.setattr(maven_fallback, "_is_windows", lambda: True)
    with_mvn(monkeypatch)
    root = write_files({"api/pom.xml": COMPANY_POM, "mvnw.cmd": "@echo off\r\n"})
    runner = FakeRunner()
    detect(root, runner)
    assert runner.calls[0][0] == str(root / "mvnw.cmd")
    assert "help:effective-pom" in runner.calls[0]


def test_windows_ignores_plain_mvnw(write_files, monkeypatch):
    monkeypatch.setattr(maven_fallback, "_is_windows", lambda: True)
    monkeypatch.setattr(maven_fallback.shutil, "which", lambda name: "C:\\maven\\bin\\mvn.cmd")
    root = write_files({"api/pom.xml": COMPANY_POM, "mvnw": "#!/bin/sh\n"})
    os.chmod(root / "mvnw", 0o755)
    runner = FakeRunner()
    detect(root, runner)
    assert runner.calls[0][0] == "C:\\maven\\bin\\mvn.cmd"


def test_mvn_on_path_is_run_by_the_full_path_which_returns(write_files, monkeypatch):
    monkeypatch.setattr(maven_fallback.shutil, "which", lambda name: "/opt/maven/bin/mvn")
    root = write_files({"api/pom.xml": COMPANY_POM})
    runner = FakeRunner()
    detect(root, runner)
    assert runner.calls[0][0] == "/opt/maven/bin/mvn"


def test_non_windows_ignores_mvnw_cmd_and_non_executable_mvnw(write_files, monkeypatch):
    monkeypatch.setattr(maven_fallback, "_is_windows", lambda: False)
    monkeypatch.setattr(maven_fallback.shutil, "which", lambda name: None)
    root = write_files({"api/pom.xml": COMPANY_POM, "mvnw.cmd": "x", "mvnw": "#!/bin/sh\n"})
    os.chmod(root / "mvnw", 0o644)
    assert maven_fallback.find_maven(root / "api" / "pom.xml", root) is None


def test_no_gaps_no_run(write_files, monkeypatch):
    with_mvn(monkeypatch)
    root = write_files({"api/pom.xml": COMPLETE_POM})
    runner = FakeRunner()
    result = detect(root, runner)
    assert runner.calls == []
    assert [f.component for f in result.findings] == ["Spring Boot", "Java"]


def test_runner_exception_is_failure(write_files, monkeypatch):
    with_mvn(monkeypatch)
    root = write_files({"api/pom.xml": COMPANY_POM})

    def boom(cmd, cwd):
        raise subprocess.TimeoutExpired(cmd, 180)

    result = detect(root, boom)
    assert all(u.reason.endswith("(Maven fallback failed)") for u in result.unrecognised)


BOOT_POM_VERSIONLESS_HIBERNATE = """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <parent><groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter-parent</artifactId><version>3.3.2</version></parent>
  <artifactId>api</artifactId>
  <properties><java.version>17</java.version></properties>
  <dependencies>
    <dependency><groupId>org.hibernate.orm</groupId><artifactId>hibernate-core</artifactId></dependency>
  </dependencies>
</project>"""


def test_fallback_fills_versionless_declaration(write_files, monkeypatch):
    with_mvn(monkeypatch)
    root = write_files({"api/pom.xml": BOOT_POM_VERSIONLESS_HIBERNATE})
    result = detect(root, FakeRunner())
    assert result.findings == [
        Finding("Spring Boot", "spring-boot", "3.3.2", "3.3.2", Path("api/pom.xml"),
                origin="spring-boot-starter-parent (parent)"),
        Finding("Java", "eclipse-temurin", "17", "17", Path("api/pom.xml"), origin="java.version"),
        Finding("Hibernate ORM", "hibernate-orm", "6.5.2", "6.5.2.Final", Path("api/pom.xml"), via_maven=True,
                origin="hibernate-core"),
    ]
    assert result.unrecognised == []


JACKSON = product("jackson-databind", "Jackson Databind", ["pkg:maven/com.fasterxml.jackson.core/jackson-databind"])
JACKSON_KEY = "maven:com.fasterxml.jackson.core/jackson-databind"
COMPANY_POM_JACKSON = """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <parent><groupId>com.acme</groupId><artifactId>acme-parent</artifactId><version>5</version></parent>
  <artifactId>api</artifactId>
  <properties><java.version>17</java.version></properties>
  <dependencies>
    <dependency><groupId>com.fasterxml.jackson.core</groupId><artifactId>jackson-databind</artifactId></dependency>
  </dependencies>
</project>"""
EFFECTIVE_JACKSON = """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <artifactId>api</artifactId>
  <properties><java.version>17</java.version></properties>
  <dependencies>
    <dependency><groupId>com.fasterxml.jackson.core</groupId><artifactId>jackson-databind</artifactId><version>2.17.0</version></dependency>
  </dependencies>
</project>"""


def detect_idx(root, runner, *products):
    det = MavenDetector(runner=runner, tmp_dir=root)
    return det.detect(root / "api/pom.xml", Context(root, use_maven=True, index=index(*products)))


def test_fallback_fills_generic_gap(write_files, monkeypatch):
    with_mvn(monkeypatch)
    root = write_files({"api/pom.xml": COMPANY_POM_JACKSON})
    result = detect_idx(root, FakeRunner(EFFECTIVE_JACKSON), JACKSON)
    assert result.dependencies == [
        Dependency(JACKSON_KEY, "jackson-databind", "2.17.0", "2.17.0", Path("api/pom.xml"), via_maven=True)]
    assert result.unrecognised == []


def test_generic_gap_without_maven(write_files, monkeypatch):
    monkeypatch.setattr(maven_fallback.shutil, "which", lambda name: None)
    root = write_files({"api/pom.xml": COMPANY_POM_JACKSON})
    result = detect_idx(root, FakeRunner(), JACKSON)
    assert result.unrecognised == [Unrecognised(
        Path("api/pom.xml"), "Jackson Databind version is set by a parent pom or BOM (Maven not found)")]
    assert result.dependencies == [Dependency(JACKSON_KEY, "jackson-databind", None, None, Path("api/pom.xml"))]


def test_generic_gap_maven_without_the_dependency(write_files, monkeypatch):
    with_mvn(monkeypatch)
    root = write_files({"api/pom.xml": COMPANY_POM_JACKSON})
    result = detect_idx(root, FakeRunner(), JACKSON)
    assert result.unrecognised == [Unrecognised(
        Path("api/pom.xml"), "Jackson Databind version is set by a parent pom or BOM")]
    assert [d.version for d in result.dependencies] == [None]


HIBERNATE = product("hibernate-orm", "Hibernate ORM", ["pkg:maven/org.hibernate.orm/hibernate-envers"])
ENVERS_KEY = "maven:org.hibernate.orm/hibernate-envers"
BOOT_POM_ENVERS = BOOT_POM_VERSIONLESS_HIBERNATE.replace("hibernate-core", "hibernate-envers")
EFFECTIVE_ENVERS = EFFECTIVE.replace("hibernate-core", "hibernate-envers")


def test_fallback_fills_special_product_gap(write_files, monkeypatch):
    with_mvn(monkeypatch)
    root = write_files({"api/pom.xml": BOOT_POM_ENVERS})
    result = detect_idx(root, FakeRunner(EFFECTIVE_ENVERS), HIBERNATE)
    assert result.unrecognised == []
    assert result.dependencies == [
        Dependency(ENVERS_KEY, "hibernate-envers", "6.5.2", "6.5.2.Final", Path("api/pom.xml"), via_maven=True)]


def test_versionless_declaration_without_maven(write_files, monkeypatch):
    monkeypatch.setattr(maven_fallback.shutil, "which", lambda name: None)
    root = write_files({"api/pom.xml": BOOT_POM_VERSIONLESS_HIBERNATE})
    result = detect(root, FakeRunner())
    assert result.unrecognised == [
        Unrecognised(Path("api/pom.xml"), "Hibernate ORM version is set by Spring Boot (Maven not found)")]
