"""Shared data types."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# Component name -> endoflife.date product slug. Order is the table order.
COMPONENTS: dict[str, str] = {
    "Spring Boot": "spring-boot",
    "Spring Framework": "spring-framework",
    "Java": "eclipse-temurin",
    "Hibernate ORM": "hibernate-orm",
    "Apache Tomcat": "tomcat",
    ".NET": "dotnet",
    ".NET Framework": "dotnetfx",
    "Angular": "angular",
    "AngularJS": "angularjs",
    "React": "react",
    "Next.js": "nextjs",
    "Node.js": "nodejs",
    "PHP": "php",
    "Laravel": "laravel",
    "Symfony": "symfony",
}


@dataclass(frozen=True)
class Finding:
    component: str
    product: str
    version: str  # normalised, used for matching
    display: str  # what the Version column shows
    source: Path  # relative to the scan root
    via_maven: bool = False


@dataclass(frozen=True)
class Unrecognised:
    source: Path
    reason: str


@dataclass(frozen=True)
class Dependency:
    ecosystem: str  # "npm" | "Maven" | "Composer" | "NuGet" | "Docker"
    name: str  # npm name; "group:artifact"; "vendor/pkg"; NuGet id; image ref without tag/digest
    version: str | None  # normalised for matching; None when unreadable
    display: str  # what the Version column shows
    source: Path  # relative to the scan root
    via_maven: bool = False
    missing: str | None = None  # short reason when version is None
    tag: str | None = None  # Docker only: full tag, for OS rows


@dataclass
class DetectResult:
    findings: list[Finding] = field(default_factory=list)
    dependencies: list[Dependency] = field(default_factory=list)
    unrecognised: list[Unrecognised] = field(default_factory=list)

    def extend(self, other: DetectResult) -> None:
        self.findings.extend(other.findings)
        self.dependencies.extend(other.dependencies)
        self.unrecognised.extend(other.unrecognised)


def finding(component: str, version: str, display: str, source: Path, via_maven: bool = False) -> Finding:
    return Finding(component, COMPONENTS[component], version, display, source, via_maven)
