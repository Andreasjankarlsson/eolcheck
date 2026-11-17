"""Every declared Maven dependency, plus the Java runtime, from pom.xml."""
from __future__ import annotations

import os
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, replace
from pathlib import Path

from ..models import DetectResult, Dependency, Unrecognised, finding
from ..versions import normalise
from . import Context
from ._util import parse_error, rel
from .maven_fallback import Runner, effective_pom, find_maven, run_subprocess

JAVA_PROPS = ("maven.compiler.release", "maven.compiler.source", "java.version")
INHERITABLE = ("Java",)
SET_BY_PARENT = "set by parent pom"
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
    props: dict[str, str] = field(default_factory=dict)  # merged properties, for child poms
    gaps: list[tuple[str, Unrecognised]] = field(default_factory=list)  # (component, gap)


@dataclass(frozen=True)
class _Coord:
    group: str
    artifact: str
    version: str | None
    section: str  # "parent", "dependency", "managed"


def read_pom(pom_xml: str | bytes, source: Path, parent_props: dict[str, str], *, check_java: bool,
             inherited: dict[str, str] | None = None) -> PomReading:
    """Read one pom. `inherited` holds the Java version already covered by an in-repo parent."""
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
    props["project.groupId"] = _text(root, "groupId") or (_text(parent, "groupId") if parent is not None else None) or ""
    props["project.artifactId"] = _text(root, "artifactId") or ""

    result = DetectResult(dependencies=_dependencies(root, props, source))
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

    java_raw = next((own_props[k] for k in JAVA_PROPS if own_props.get(k)), None) or _compiler_setting(root)
    if java_raw:
        add("Java", java_raw, parse=java_version)
    elif check_java and _text(root, "packaging") != "pom" and "Java" not in inherited \
            and not any(props.get(k) for k in JAVA_PROPS):
        add_gap("Java", "couldn't read the Java version")

    has_gaps = bool(gaps) or any(d.version is None for d in result.dependencies)
    return PomReading(result, has_gaps, props, gaps)


def _dependencies(root: ET.Element, props: dict[str, str], source: Path) -> list[Dependency]:
    """The parent, <dependencies> and <dependencyManagement> entries, once per group:artifact."""
    out: dict[str, Dependency] = {}
    for c in _coords(root):
        group, group_missing = _resolve(c.group, props)
        artifact, artifact_missing = _resolve(c.artifact, props)
        if not group or not artifact or group_missing or artifact_missing:
            continue  # no usable name
        name = f"{group}:{artifact}"
        dependency = _dependency(name, c.version, props, source)
        if name not in out or (out[name].version is None and dependency.version is not None):
            out[name] = dependency  # e.g. a versionless <dependency> with its version in this pom's <dependencyManagement>
    return list(out.values())


def _dependency(name: str, raw: str | None, props: dict[str, str], source: Path) -> Dependency:
    if not raw:
        return Dependency("Maven", name, None, SET_BY_PARENT, source, missing=SET_BY_PARENT)
    value, missing = _resolve(raw, props)
    if missing:
        return Dependency("Maven", name, None, raw, source, missing=f"couldn't resolve ${{{missing}}}")
    version = normalise(value)
    if version is None:
        return Dependency("Maven", name, None, value, source, missing=f"'{value}' isn't a version")
    return Dependency("Maven", name, version, value, source)


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
        print(f"Asking Maven about {rel(path, ctx)}…", file=sys.stderr, flush=True)
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
        # Fill only what this file declares; the effective pom also lists inherited dependencies.
        effective_versions = {d.name: d for d in effective.result.dependencies if d.version is not None}
        for d in reading.result.dependencies:
            e = effective_versions.get(d.name) if d.version is None else None
            result.dependencies.append(
                replace(d, version=e.version, display=e.display, via_maven=True, missing=None) if e else d)
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
    """Say why Maven didn't help: '(Maven not found)' on gaps, ', Maven not found' on dependencies."""
    plain = suffix.strip().strip("()")
    return DetectResult(
        findings=list(reading.result.findings),
        dependencies=[replace(d, missing=f"{d.missing}, {plain}") if d.missing else d
                      for d in reading.result.dependencies],
        unrecognised=[Unrecognised(u.source, u.reason + suffix) for _, u in reading.gaps],
    )


def _parent_chain(path: Path, text: str | bytes, root: Path, depth: int = 0) -> tuple[dict[str, str], dict[str, str]]:
    """Merged properties and the inherited Java version from parent poms inside the repo."""
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
    """The parent, <dependencies> and <dependencyManagement> entries. Plugins are build tools, so not included."""
    out: list[_Coord] = []
    paths = [
        (("parent",), "parent"),
        (("dependencies", "dependency"), "dependency"),
        (("dependencyManagement", "dependencies", "dependency"), "managed"),
    ]
    for path, section in paths:
        for el in _walk(root, path):
            out.append(_Coord(_text(el, "groupId") or "", _text(el, "artifactId") or "", _text(el, "version"), section))
    return out


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
