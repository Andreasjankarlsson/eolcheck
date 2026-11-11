"""Spring Boot, Spring Framework, Java, Hibernate ORM and Tomcat from pom.xml."""
from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, replace
from pathlib import Path

from ..models import DetectResult, Unrecognised, finding
from ..versions import normalise
from . import Context
from ._util import parse_error, rel
from .maven_fallback import Runner, effective_pom, find_maven, run_subprocess

BOOT_GROUP = "org.springframework.boot"
JAVA_PROPS = ("maven.compiler.release", "maven.compiler.source", "java.version")
INHERITABLE = ("Spring Boot", "Java")
_PROP_REF = re.compile(r"\$\{([^}]+)\}")


def java_version(raw: str) -> str | None:
    """'1.8' -> '8', '17' -> '17', '21.0.1' -> '21'."""
    if not raw or "${" in raw:
        return None
    v = normalise(raw)
    if v is None:
        return None
    parts = v.split(".")
    return parts[1] if parts[0] == "1" and len(parts) > 1 else parts[0]


@dataclass
class PomReading:
    result: DetectResult
    has_gaps: bool
    gap_components: set[str] = field(default_factory=set)
    props: dict[str, str] = field(default_factory=dict)  # merged properties, for child poms
    gaps: list[tuple[str, Unrecognised]] = field(default_factory=list)  # (component, gap)


@dataclass(frozen=True)
class _Coord:
    group: str
    artifact: str
    version: str | None
    section: str  # "dependency", "managed", "plugin"


def read_pom(pom_xml: str | bytes, source: Path, parent_props: dict[str, str], *, check_java: bool,
             inherited: dict[str, str] | None = None) -> PomReading:
    """Read one pom. `inherited` holds Spring Boot / Java versions already covered by an in-repo parent."""
    inherited = inherited or {}
    root = ET.fromstring(pom_xml)

    own_props = {_local(c.tag): (c.text or "").strip() for p in _kids(root, "properties") for c in p}
    parent = _first(root, "parent")
    parent_version = _text(parent, "version") if parent is not None else None
    props = dict(parent_props)
    props.update(own_props)
    if parent_version:
        props["project.parent.version"] = parent_version
    props["project.version"] = _text(root, "version") or parent_version or ""

    coords = _coords(root)
    result = DetectResult()
    gaps: list[tuple[str, Unrecognised]] = []

    def add_gap(component: str, reason: str) -> None:
        gap_entry = Unrecognised(source, reason)
        result.unrecognised.append(gap_entry)
        gaps.append((component, gap_entry))

    def add(component: str, raw: str, parse=normalise) -> None:
        value, missing = _resolve(raw, props)
        if missing:
            add_gap(component, f"couldn't resolve ${{{missing}}}")
            return
        version = parse(value)
        if version is None:
            add_gap(component, f"couldn't read the {component} version")
            return
        result.findings.append(finding(component, version, value, source))

    # Spring Boot
    boot_raw = None
    if parent is not None and _text(parent, "groupId") == BOOT_GROUP \
            and _text(parent, "artifactId") == "spring-boot-starter-parent":
        boot_raw = parent_version
    boot_raw = boot_raw or _version_of(coords, BOOT_GROUP, {"spring-boot-dependencies"}, sections={"managed"})
    boot_raw = boot_raw or next((c.version for c in coords if c.group == BOOT_GROUP and c.version), None)
    uses_boot = boot_raw is not None or any(c.group == BOOT_GROUP for c in coords)
    if boot_raw:
        add("Spring Boot", boot_raw)
    elif uses_boot and "Spring Boot" not in inherited:
        add_gap("Spring Boot", "couldn't read the Spring Boot version")

    # Spring Framework: only when pinned explicitly
    sf_raw = _version_of(coords, "org.springframework", {"spring-framework-bom"}, sections={"managed"}) or next(
        (c.version for c in coords
         if c.group == "org.springframework" and c.artifact.startswith("spring-") and c.version), None)
    if sf_raw:
        add("Spring Framework", sf_raw)

    # Java
    java_raw = next((own_props[k] for k in JAVA_PROPS if own_props.get(k)), None) or _compiler_setting(root)
    if java_raw:
        add("Java", java_raw, parse=java_version)
    elif check_java and _text(root, "packaging") != "pom" and "Java" not in inherited \
            and not any(props.get(k) for k in JAVA_PROPS):
        add_gap("Java", "couldn't read the Java version")

    # Hibernate ORM and Tomcat: only when pinned explicitly
    hib_raw = next((c.version for c in coords if c.group in ("org.hibernate", "org.hibernate.orm")
                    and c.artifact == "hibernate-core" and c.version), None)
    if hib_raw:
        add("Hibernate ORM", hib_raw)
    tomcat_raw = _version_of(coords, "org.apache.tomcat.embed", {"tomcat-embed-core"}) or own_props.get("tomcat.version")
    if tomcat_raw:
        add("Apache Tomcat", tomcat_raw)

    return PomReading(result, bool(gaps), {c for c, _ in gaps}, props, gaps)


class MavenDetector:
    def __init__(self, runner: Runner | None = None, tmp_dir: Path | None = None):
        self._runner = runner or run_subprocess
        self._tmp_dir = tmp_dir

    def applies_to(self, path: Path) -> bool:
        return path.name == "pom.xml"

    def detect(self, path: Path, ctx: Context) -> DetectResult:
        try:
            # Bytes, so the XML parser honours the file's own encoding declaration (e.g. ISO-8859-1).
            text = path.read_bytes()
            props, inherited = _parent_chain(path, text, ctx.root)
            reading = read_pom(text, rel(path, ctx), props, check_java=True, inherited=inherited)
        except ET.ParseError:
            return parse_error(path, ctx)
        return self._after_direct_read(path, ctx, reading)

    def _after_direct_read(self, path: Path, ctx: Context, reading: PomReading) -> DetectResult:
        """If reading the file directly left gaps, ask Maven for the effective pom."""
        if not reading.has_gaps or not ctx.use_maven:
            return reading.result
        if find_maven(path, ctx.root) is None:
            return _with_suffix(reading, " (Maven not found)")
        text = effective_pom(path, ctx.root, self._runner, self._tmp_dir)
        effective = _read_effective(text, rel(path, ctx)) if text else None
        if effective is None:
            return _with_suffix(reading, " (Maven fallback failed)")

        found = {}
        for f in effective.result.findings:
            found.setdefault(f.component, replace(f, via_maven=True))
        result = DetectResult(findings=list(reading.result.findings))
        for component, gap_entry in reading.gaps:
            if component in found:
                result.findings.append(found.pop(component))
            else:
                result.unrecognised.append(gap_entry)
        return result


def _read_effective(text: str, source: Path) -> PomReading | None:
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return None
    if _local(root.tag) == "projects":  # multi-module output: take the first project
        projects = _kids(root, "project")
        if not projects:
            return None
        text = ET.tostring(projects[0], encoding="unicode")
    try:
        return read_pom(text, source, {}, check_java=True)
    except ET.ParseError:
        return None


def _with_suffix(reading: PomReading, suffix: str) -> DetectResult:
    return DetectResult(
        findings=list(reading.result.findings),
        unrecognised=[Unrecognised(u.source, u.reason + suffix) for _, u in reading.gaps],
    )


def _parent_chain(path: Path, text: str | bytes, root: Path, depth: int = 0) -> tuple[dict[str, str], dict[str, str]]:
    """Merged properties and inherited Spring Boot/Java versions from parent poms inside the repo."""
    if depth > 10:
        return {}, {}
    try:
        parent = _first(ET.fromstring(text), "parent")
    except ET.ParseError:
        return {}, {}
    if parent is None:
        return {}, {}
    rel_el = _first(parent, "relativePath")
    if rel_el is not None and not (rel_el.text or "").strip():
        return {}, {}  # <relativePath/> means: don't look locally
    rel_path = (rel_el.text or "").strip() if rel_el is not None else "../pom.xml"
    candidate = Path(os.path.normpath(path.parent / rel_path))
    if candidate.is_dir():
        candidate = candidate / "pom.xml"
    root_abs = Path(os.path.normpath(root))
    if candidate == path or root_abs not in candidate.parents or not candidate.is_file():
        return {}, {}
    try:
        parent_text = candidate.read_bytes()
        if _text(ET.fromstring(parent_text), "artifactId") != _text(parent, "artifactId"):
            return {}, {}
        grand_props, grand_inherited = _parent_chain(candidate, parent_text, root, depth + 1)
        reading = read_pom(parent_text, candidate, grand_props, check_java=False, inherited=grand_inherited)
    except ET.ParseError:
        return {}, {}
    inherited = dict(grand_inherited)
    inherited.update({f.component: f.version for f in reading.result.findings if f.component in INHERITABLE})
    return reading.props, inherited


def _resolve(raw: str, props: dict[str, str]) -> tuple[str, str | None]:
    value = raw.strip()
    for _ in range(6):
        new = _PROP_REF.sub(lambda m: props.get(m.group(1), m.group(0)), value)
        if new == value:
            break
        value = new
    missing = _PROP_REF.search(value)
    return value, (missing.group(1) if missing else None)


def _coords(root: ET.Element) -> list[_Coord]:
    out: list[_Coord] = []
    paths = [
        (("dependencies", "dependency"), "dependency"),
        (("dependencyManagement", "dependencies", "dependency"), "managed"),
        (("build", "plugins", "plugin"), "plugin"),
        (("build", "pluginManagement", "plugins", "plugin"), "plugin"),
    ]
    for path, section in paths:
        for el in _walk(root, path):
            out.append(_Coord(_text(el, "groupId") or "", _text(el, "artifactId") or "", _text(el, "version"), section))
    return out


def _version_of(coords: list[_Coord], group: str, artifacts: set[str], sections: set[str] | None = None) -> str | None:
    for c in coords:
        if c.group == group and c.artifact in artifacts and c.version and (sections is None or c.section in sections):
            return c.version
    return None


def _compiler_setting(root: ET.Element) -> str | None:
    for path in (("build", "plugins", "plugin"), ("build", "pluginManagement", "plugins", "plugin")):
        for plugin in _walk(root, path):
            if _text(plugin, "artifactId") != "maven-compiler-plugin":
                continue
            config = _first(plugin, "configuration")
            if config is not None:
                value = _text(config, "release") or _text(config, "source")
                if value:
                    return value
    return None


def _local(tag) -> str:
    return tag.split("}")[-1] if isinstance(tag, str) else ""


def _kids(el: ET.Element, name: str) -> list[ET.Element]:
    return [c for c in el if _local(c.tag) == name]


def _first(el: ET.Element, name: str) -> ET.Element | None:
    kids = _kids(el, name)
    return kids[0] if kids else None


def _text(el: ET.Element | None, name: str) -> str | None:
    if el is None:
        return None
    child = _first(el, name)
    return child.text.strip() if child is not None and child.text and child.text.strip() else None


def _walk(el: ET.Element, path: tuple[str, ...]) -> list[ET.Element]:
    current = [el]
    for name in path:
        current = [k for c in current for k in _kids(c, name)]
    return current
