import os
import subprocess
from pathlib import Path

from eolchecker.detectors import Context
from eolchecker.detectors import maven_fallback
from eolchecker.detectors.maven import MavenDetector
from eolchecker.models import Dependency, Finding, Unrecognised

STARTER = "org.springframework.boot:spring-boot-starter-web"

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
    src = Path("api/pom.xml")
    assert result.findings == [Finding("Java", "eclipse-temurin", "17", "17", src, via_maven=True)]
    # Only what the file declares: the inherited hibernate-core from the effective pom is not added.
    assert result.dependencies == [
        Dependency("Maven", "com.acme:acme-parent", "5", "5", src),
        Dependency("Maven", STARTER, "3.3.2", "3.3.2", src, via_maven=True),
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
    assert result.unrecognised == [Unrecognised(Path("api/pom.xml"), "couldn't read the Java version")]
    assert starter(result).missing == "set by parent pom"


def starter(result):
    return next(d for d in result.dependencies if d.name == STARTER)


def test_fallback_failure_keeps_gap(write_files, monkeypatch):
    with_mvn(monkeypatch)
    root = write_files({"api/pom.xml": COMPANY_POM})
    result = detect(root, FakeRunner(returncode=1))
    assert result.unrecognised == [
        Unrecognised(Path("api/pom.xml"), "couldn't read the Java version (Maven fallback failed)")]
    assert starter(result) == Dependency("Maven", STARTER, None, "set by parent pom", Path("api/pom.xml"),
                                         missing="set by parent pom, Maven fallback failed")


def test_maven_not_found(write_files, monkeypatch):
    monkeypatch.setattr(maven_fallback.shutil, "which", lambda name: None)
    root = write_files({"api/pom.xml": COMPANY_POM})
    runner = FakeRunner()
    result = detect(root, runner)
    assert runner.calls == []
    assert result.unrecognised == [Unrecognised(Path("api/pom.xml"), "couldn't read the Java version (Maven not found)")]
    assert starter(result).missing == "set by parent pom, Maven not found"


def test_prefers_mvnw(write_files, monkeypatch):
    with_mvn(monkeypatch)
    root = write_files({"api/pom.xml": COMPANY_POM, "mvnw": "#!/bin/sh\n"})
    os.chmod(root / "mvnw", 0o755)
    runner = FakeRunner()
    detect(root, runner)
    assert runner.calls[0][0] == str(root / "mvnw")
    assert "help:effective-pom" in runner.calls[0]
    assert "-N" in runner.calls[0]


def test_no_gaps_no_run(write_files, monkeypatch):
    with_mvn(monkeypatch)
    root = write_files({"api/pom.xml": COMPLETE_POM})
    runner = FakeRunner()
    result = detect(root, runner)
    assert runner.calls == []
    assert [f.component for f in result.findings] == ["Java"]
    assert [d.version for d in result.dependencies] == ["3.3.2"]


def test_runner_exception_is_failure(write_files, monkeypatch):
    with_mvn(monkeypatch)
    root = write_files({"api/pom.xml": COMPANY_POM})

    def boom(cmd, cwd):
        raise subprocess.TimeoutExpired(cmd, 180)

    result = detect(root, boom)
    assert result.unrecognised and all(u.reason.endswith("(Maven fallback failed)") for u in result.unrecognised)
    assert starter(result).missing == "set by parent pom, Maven fallback failed"


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
    runner = FakeRunner()
    result = detect(root, runner)
    src = Path("api/pom.xml")
    assert len(runner.calls) == 1
    assert result.findings == [Finding("Java", "eclipse-temurin", "17", "17", src)]
    assert result.dependencies == [
        Dependency("Maven", "org.springframework.boot:spring-boot-starter-parent", "3.3.2", "3.3.2", src),
        Dependency("Maven", "org.hibernate.orm:hibernate-core", "6.5.2", "6.5.2.Final", src, via_maven=True),
    ]
    assert result.unrecognised == []


def test_versionless_declaration_without_maven(write_files, monkeypatch):
    monkeypatch.setattr(maven_fallback.shutil, "which", lambda name: None)
    root = write_files({"api/pom.xml": BOOT_POM_VERSIONLESS_HIBERNATE})
    result = detect(root, FakeRunner())
    assert result.unrecognised == []
    hib = next(d for d in result.dependencies if d.name == "org.hibernate.orm:hibernate-core")
    assert hib.missing == "set by parent pom, Maven not found"
