"""Every dependency and plugin in pom.xml, plus the special cases Spring Boot, Spring Framework,
Java, Hibernate ORM and Tomcat."""
from __future__ import annotations

import os
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, replace
from pathlib import Path

from ..catalog import PurlIndex, dep_key
from ..models import COMPONENTS, DetectResult, Dependency, Unrecognised, finding
from ..versions import normalise
from . import Context
from ._util import parse_error, rel
from .maven_fallback import Runner, effective_pom, find_maven, run_subprocess

BOOT_GROUP = "org.springframework.boot"
JAVA_PROPS = ("maven.compiler.release", "maven.compiler.source", "java.version")
INHERITABLE = ("Spring Boot", "Java")
# Products whose gaps the special-case code below already reports.
SPECIAL_SLUGS = frozenset({"spring-boot", "spring-framework", "hibernate-orm", "tomcat"})
DEFAULT_PLUGIN_GROUP = "org.apache.maven.plugins"
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
    # (component, gap) for the special cases; (dependency key, gap) for other dependencies
    gaps: list[tuple[str, Unrecognised]] = field(default_factory=list)
    products: set[str] = field(default_factory=set)  # slugs reported with a version, here or by parents
    managed: dict[str, str] = field(default_factory=dict)  # dependency key -> raw managed version


@dataclass(frozen=True)
class _Coord:
    group: str
    artifact: str
    version: str | None
    section: str  # "dependency", "managed", "plugin", "managed-plugin"
    scope: str | None = None

    @property
    def key(self) -> str:
        return dep_key("maven", f"{self.group}/{self.artifact}")


def read_pom(pom_xml: str | bytes, source: Path, parent_props: dict[str, str], *, check_java: bool,
             inherited: dict[str, str] | None = None, index: PurlIndex | None = None,
             parent_products: frozenset[str] | set[str] = frozenset(),
             parent_managed: dict[str, str] | None = None) -> PomReading:
    """Read one pom. `inherited` holds Spring Boot / Java versions already covered by an in-repo parent;
    `parent_products` and `parent_managed` the products and managed versions of the in-repo parent chain."""
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
    parent_managed = parent_managed or {}
    managed = dict(parent_managed)
    managed.update(_managed(coords))
    result = DetectResult()
    gaps: list[tuple[str, Unrecognised]] = []
    gap_components: set[str] = set()

    def add_gap(component: str, reason: str, key: str | None = None) -> None:
        gap_entry = Unrecognised(source, reason)
        result.unrecognised.append(gap_entry)
        gaps.append((key or component, gap_entry))
        gap_components.add(component)

    def add(component: str, raw: str, origin: str, parse=normalise) -> None:
        value, missing = _resolve(raw, props)
        if missing:
            add_gap(component, f"couldn't resolve ${{{missing}}}")
            return
        version = parse(value)
        if version is None:
            add_gap(component, f"couldn't read the {component} version")
            return
        result.findings.append(finding(component, version, value, source, origin=origin))

    def first_versioned(matches, sections: set[str] | None = None) -> _Coord | None:
        return next((c for c in coords if c.version and matches(c) and (sections is None or c.section in sections)),
                    None)

    # Spring Boot
    boot_raw = boot_origin = None
    if parent is not None and _text(parent, "groupId") == BOOT_GROUP \
            and _text(parent, "artifactId") == "spring-boot-starter-parent":
        boot_raw, boot_origin = parent_version, "spring-boot-starter-parent (parent)"
    if not boot_raw:
        c = first_versioned(lambda c: c.group == BOOT_GROUP and c.artifact == "spring-boot-dependencies",
                            {"managed"}) or first_versioned(lambda c: c.group == BOOT_GROUP)
        boot_raw, boot_origin = (c.version, c.artifact) if c else (None, None)
    uses_boot = boot_raw is not None or any(c.group == BOOT_GROUP for c in coords)
    if boot_raw:
        add("Spring Boot", boot_raw, boot_origin)
    elif uses_boot and "Spring Boot" not in inherited:
        add_gap("Spring Boot", "couldn't read the Spring Boot version")

    boot_managed = boot_raw is not None or "Spring Boot" in inherited

    def set_by(component: str) -> str:
        return f"{component} version is set by " + ("Spring Boot" if boot_managed else "a parent pom or BOM")

    def declared_without_version(component: str, matches) -> None:
        """Declared in <dependencies> without a version: take it from an in-repo parent's
        <dependencyManagement>, else it comes from a parent or BOM and is a gap for Maven to fill."""
        declared = [c for c in coords if c.section == "dependency" and not c.version and matches(c)]
        from_parent = next((c for c in declared if c.key in parent_managed), None)
        if from_parent:
            add(component, parent_managed[from_parent.key], from_parent.artifact)
        elif declared:
            add_gap(component, set_by(component))

    def special(component: str, matches, bom: str | None = None) -> bool:
        """Add `component` from a BOM import or a versioned coordinate; False if neither has a version."""
        c = (first_versioned(lambda c: matches(c) and c.artifact == bom, {"managed"}) if bom else None) \
            or first_versioned(matches)
        if c:
            add(component, c.version, c.artifact)
        return c is not None

    # Spring Framework
    is_sf = lambda c: c.group == "org.springframework" and c.artifact.startswith("spring-")  # noqa: E731
    if not special("Spring Framework", is_sf, bom="spring-framework-bom"):
        declared_without_version("Spring Framework", is_sf)

    # Java
    java_prop = next((k for k in JAVA_PROPS if own_props.get(k)), None)
    java_raw = own_props[java_prop] if java_prop else _compiler_setting(root)
    if java_raw:
        add("Java", java_raw, java_prop or "maven-compiler-plugin", parse=java_version)
    elif check_java and _text(root, "packaging") != "pom" and "Java" not in inherited \
            and not any(props.get(k) for k in JAVA_PROPS):
        add_gap("Java", "couldn't read the Java version")

    # Hibernate ORM and Tomcat
    is_hib = lambda c: c.group in ("org.hibernate", "org.hibernate.orm") and c.artifact == "hibernate-core"  # noqa: E731
    if not special("Hibernate ORM", is_hib):
        declared_without_version("Hibernate ORM", is_hib)
    is_tomcat = lambda c: c.group == "org.apache.tomcat.embed" and c.artifact == "tomcat-embed-core"  # noqa: E731
    if not special("Apache Tomcat", is_tomcat):
        if own_props.get("tomcat.version"):
            add("Apache Tomcat", own_props["tomcat.version"], "tomcat.version")
        else:
            declared_without_version("Apache Tomcat", is_tomcat)

    # Every dependency and plugin
    products = {f.product for f in result.findings} | set(parent_products)
    # Special-case products that already have a gap in this pom.
    special_gaps = {COMPONENTS[c] for c in gap_components if COMPONENTS.get(c) in SPECIAL_SLUGS}
    deps, dep_gaps = _dependencies(coords, props, managed, index, parent_products, products, special_gaps,
                                   source, set_by)
    result.dependencies.extend(deps)
    for key, component, reason in dep_gaps:
        if component not in gap_components:  # one gap per component per pom
            add_gap(component, reason, key)
    return PomReading(result, bool(gaps), gap_components, props, gaps, products, managed)


def _dependencies(coords: list[_Coord], props: dict[str, str], managed: dict[str, str], index: PurlIndex | None,
                  parent_products: frozenset[str] | set[str], products: set[str], special_gaps: set[str],
                  source: Path, set_by) -> tuple[list[Dependency], list[tuple[str, str, str]]]:
    """Every <dependency> and <plugin> as a Dependency, plus (key, component, reason) for each tracked
    one whose version is not known here. Adds the products of versioned dependencies to `products`.
    `managed` values are raw and resolved here with this pom's properties (Maven interpolates after
    inheritance)."""
    deps: list[Dependency] = []
    gaps: list[tuple[str, str, str]] = []
    resolved = []
    for c in coords:
        if c.section not in ("dependency", "plugin") or not c.group or not c.artifact:
            continue
        raw = c.version or managed.get(c.key)
        value, missing = _resolve(raw, props) if raw else (None, None)
        version = None if missing or not value else normalise(value)
        matches = index.resolve(c.key) if index is not None else []
        if version:
            products.update(m.product for m in matches)
        resolved.append((c, value, missing, version, matches))

    for c, value, missing, version, matches in resolved:
        if version:
            deps.append(Dependency(c.key, c.artifact, version, value, source))
            continue
        if matches and all(m.product in parent_products for m in matches):
            continue  # the in-repo parent's row covers it
        deps.append(Dependency(c.key, c.artifact, None, None, source))
        if not matches or any(m.product in special_gaps or m.product in products for m in matches):
            continue  # untracked, already a special-case gap, or joins a versioned row
        component = matches[0].component
        if missing:
            reason = f"couldn't resolve ${{{missing}}}"
        elif value:
            reason = f"couldn't read the {component} version"
        else:
            reason = set_by(component)
        gaps.append((c.key, component, reason))
    return deps, gaps


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
            props, inherited, products, managed = _parent_chain(path, text, ctx.root, ctx.index)
            reading = read_pom(text, rel(path, ctx), props, check_java=True, inherited=inherited, index=ctx.index,
                               parent_products=products, parent_managed=managed)
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
        found_deps = {}
        for d in effective.result.dependencies:
            if d.version:
                found_deps.setdefault(d.key, replace(d, via_maven=True))
        result = DetectResult(findings=list(reading.result.findings))
        filled = set()
        for name, gap_entry in reading.gaps:  # name: a special-case component or a dependency key
            if name in found:
                result.findings.append(found.pop(name))
            elif name in found_deps:
                filled.add(name)
            else:
                result.unrecognised.append(gap_entry)
        result.dependencies = [found_deps[d.key] if d.key in filled and d.version is None else d
                               for d in reading.result.dependencies]
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
        dependencies=list(reading.result.dependencies),
    )


_Chain = tuple[dict[str, str], dict[str, str], set[str], dict[str, str]]


def _parent_chain(path: Path, text: str | bytes, root: Path, index: PurlIndex | None,
                  depth: int = 0) -> _Chain:
    """From parent poms inside the repo: merged properties, inherited Spring Boot/Java versions,
    the products they report with a version, and their managed versions."""
    none: _Chain = ({}, {}, set(), {})
    if depth > 10:
        return none
    try:
        parent = _first(ET.fromstring(text), "parent")
    except ET.ParseError:
        return none
    if parent is None:
        return none
    rel_el = _first(parent, "relativePath")
    if rel_el is not None and not (rel_el.text or "").strip():
        return none  # <relativePath/> means: don't look locally
    rel_path = (rel_el.text or "").strip() if rel_el is not None else "../pom.xml"
    candidate = Path(os.path.normpath(path.parent / rel_path))
    if candidate.is_dir():
        candidate = candidate / "pom.xml"
    root_abs = Path(os.path.normpath(root))
    if candidate == path or root_abs not in candidate.parents or not candidate.is_file():
        return none
    try:
        parent_text = candidate.read_bytes()
        if _text(ET.fromstring(parent_text), "artifactId") != _text(parent, "artifactId"):
            return none
        grand_props, grand_inherited, grand_products, grand_managed = _parent_chain(
            candidate, parent_text, root, index, depth + 1)
        reading = read_pom(parent_text, candidate, grand_props, check_java=False, inherited=grand_inherited,
                           index=index, parent_products=grand_products, parent_managed=grand_managed)
    except ET.ParseError:
        return none
    inherited = dict(grand_inherited)
    inherited.update({f.component: f.version for f in reading.result.findings if f.component in INHERITABLE})
    return reading.props, inherited, reading.products, reading.managed


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
        (("build", "pluginManagement", "plugins", "plugin"), "managed-plugin"),
    ]
    for path, section in paths:
        default_group = DEFAULT_PLUGIN_GROUP if "plugin" in section else ""
        for el in _walk(root, path):
            out.append(_Coord(_text(el, "groupId") or default_group, _text(el, "artifactId") or "",
                              _text(el, "version"), section, _text(el, "scope")))
    return out


def _managed(coords: list[_Coord]) -> dict[str, str]:
    """Dependency key -> raw version from <dependencyManagement> and <pluginManagement>. Left raw so a
    child pom resolves `${…}` with its own properties. BOM imports are not versions for other
    artifacts, so they are left out."""
    out: dict[str, str] = {}
    for c in coords:
        if c.section not in ("managed", "managed-plugin") or not c.group or not c.artifact or not c.version \
                or c.scope == "import":
            continue
        out.setdefault(c.key, c.version)
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
