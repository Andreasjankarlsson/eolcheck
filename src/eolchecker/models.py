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

# Dependency key -> component name, for packages whose catalogue entry would be
# ambiguous or wrongly named (see catalog.PurlIndex.resolve).
OVERRIDES: dict[str, str] = {
    "npm:@angular/core": "Angular",
    "npm:angular": "AngularJS",
    "npm:react": "React",
    "npm:next": "Next.js",
    "composer:laravel/framework": "Laravel",
    "composer:symfony/framework-bundle": "Symfony",
    "composer:symfony/http-kernel": "Symfony",
}


@dataclass(frozen=True)
class Finding:
    component: str
    product: str
    version: str  # normalised, used for matching
    display: str  # what the Version column shows
    source: Path  # relative to the scan root
    via_maven: bool = False
    origin: str = ""  # what the Dependencies column shows for a runtime/parent finding


@dataclass(frozen=True)
class Dependency:
    key: str  # "<ecosystem>:<name>", lower case (catalog.dep_key)
    name: str  # as shown in the Dependencies column
    version: str | None  # normalised
    display: str | None
    source: Path  # relative to the scan root
    via_maven: bool = False


@dataclass(frozen=True)
class Unrecognised:
    source: Path
    reason: str


@dataclass
class DetectResult:
    findings: list[Finding] = field(default_factory=list)
    unrecognised: list[Unrecognised] = field(default_factory=list)
    dependencies: list[Dependency] = field(default_factory=list)

    def extend(self, other: DetectResult) -> None:
        self.findings.extend(other.findings)
        self.unrecognised.extend(other.unrecognised)
        self.dependencies.extend(other.dependencies)


def finding(component: str, version: str, display: str, source: Path,
            via_maven: bool = False, origin: str = "") -> Finding:
    return Finding(component, COMPONENTS[component], version, display, source, via_maven, origin)
