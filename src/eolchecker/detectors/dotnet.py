""".NET and .NET Framework from project files, Directory.Build.props and global.json."""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from ..models import DetectResult, Dependency, Unrecognised, finding
from ..versions import lowest, normalise
from . import Context
from ._util import dirs_up, parse_error, read_text, rel

PROJECT_SUFFIXES = (".csproj", ".fsproj", ".vbproj")
PROPS = "Directory.Build.props"
CENTRAL = "Directory.Packages.props"
NO_TARGET = "couldn't read the .NET target framework"
_PROP_REF = re.compile(r"\$\(([^)]+)\)")


def parse_tfm(tfm: str) -> tuple[str, str] | None:
    """'net8.0' -> ('.NET', '8.0'), 'net472' -> ('.NET Framework', '4.7.2'); None if not recognised."""
    t = tfm.strip().lower().split("-")[0]
    if m := re.fullmatch(r"netcoreapp(\d+\.\d+)", t):
        return (".NET", m.group(1))
    if (m := re.fullmatch(r"net(\d+)\.(\d+)", t)) and int(m.group(1)) >= 5:
        return (".NET", f"{m.group(1)}.{m.group(2)}")
    if m := re.fullmatch(r"net(\d)(\d)(\d)?", t):
        return (".NET Framework", ".".join(g for g in m.groups() if g))
    if m := re.fullmatch(r"v(\d+(?:\.\d+)+)", t):
        return (".NET Framework", m.group(1))
    return None


class DotnetDetector:
    def applies_to(self, path: Path) -> bool:
        return path.suffix in PROJECT_SUFFIXES or path.name in ("global.json", "packages.config")

    def detect(self, path: Path, ctx: Context) -> DetectResult:
        if path.name == "global.json":
            return self._global_json(path, ctx)
        if path.name == "packages.config":
            return self._packages_config(path, ctx)
        try:
            project_props = _properties(path)
        except ET.ParseError:
            return parse_error(path, ctx)

        result = DetectResult()
        props: dict[str, str] = {}
        for props_file in reversed(_props_chain(path.parent, ctx.root)):
            try:
                props.update(_properties(props_file))
            except ET.ParseError:
                result.unrecognised.append(Unrecognised(rel(props_file, ctx), f"couldn't parse {PROPS}"))
        props.update(project_props)

        source = rel(path, ctx)
        self._package_references(path, ctx, props, result)

        raw = props.get("TargetFrameworks") or props.get("TargetFramework") or props.get("TargetFrameworkVersion")
        if not raw:
            result.unrecognised.append(Unrecognised(source, NO_TARGET))
            return result
        raw = _resolve(raw, props)

        for tfm in (t.strip() for t in raw.split(";")):
            if not tfm or tfm.lower().startswith("netstandard"):
                continue
            parsed = parse_tfm(tfm)
            if parsed is None:
                result.unrecognised.append(Unrecognised(source, NO_TARGET))
                continue
            component, version = parsed
            result.findings.append(finding(component, version, tfm, source))
        return result

    def _package_references(self, path: Path, ctx: Context, props: dict[str, str], result: DetectResult) -> None:
        """List every PackageReference; versions may come from Directory.Packages.props."""
        source = rel(path, ctx)
        central: dict[str, str] | None = None
        for item in ET.fromstring(path.read_bytes()).iter():
            if _local(item.tag) != "PackageReference":
                continue
            name = item.get("Include")
            if not name:
                continue
            raw = item.get("Version") or _child_text(item, "Version")
            if raw is None:
                if central is None:
                    central = _central_versions(path.parent, ctx, result)
                raw = central.get(name)
            if raw is None:
                result.dependencies.append(Dependency(
                    "NuGet", name, None, "", source, missing=f"no version in project or {CENTRAL}"))
                continue
            _add_nuget(result, name, _resolve(raw, props), source)

    def _packages_config(self, path: Path, ctx: Context) -> DetectResult:
        try:
            root = ET.fromstring(path.read_bytes())
        except ET.ParseError:
            return parse_error(path, ctx)
        result = DetectResult()
        for pkg in root.iter():
            if _local(pkg.tag) == "package" and pkg.get("id"):
                _add_nuget(result, pkg.get("id"), pkg.get("version") or "", rel(path, ctx))
        return result

    def _global_json(self, path: Path, ctx: Context) -> DetectResult:
        try:
            data = json.loads(read_text(path))
        except ValueError:
            return parse_error(path, ctx)
        sdk = (data.get("sdk") or {}).get("version") if isinstance(data, dict) else None
        if not isinstance(sdk, str):
            return DetectResult()
        version = normalise(sdk)
        if version is None:
            return DetectResult(unrecognised=[Unrecognised(rel(path, ctx), "couldn't read the .NET SDK version")])
        return DetectResult(findings=[finding(".NET", version, f"SDK {sdk}", rel(path, ctx))])


def _properties(path: Path) -> dict[str, str]:
    """All <PropertyGroup> values in an MSBuild file, ignoring XML namespaces."""
    # Bytes, so the XML parser honours the file's own encoding (UTF-16 in some older Visual Studio files).
    root = ET.fromstring(path.read_bytes())
    out: dict[str, str] = {}
    for group in root.iter():
        if _local(group.tag) != "PropertyGroup":
            continue
        for child in group:
            if child.text and child.text.strip():
                out[_local(child.tag)] = child.text.strip()
    return out


def _add_nuget(result: DetectResult, name: str, raw: str, source: Path) -> None:
    version = lowest(raw)
    if version is None:
        result.dependencies.append(Dependency("NuGet", name, None, raw, source, missing=f"'{raw}' isn't a version"))
    else:
        result.dependencies.append(Dependency("NuGet", name, version, raw, source))


def _child_text(item, tag: str) -> str | None:
    for child in item:
        if _local(child.tag) == tag and child.text and child.text.strip():
            return child.text.strip()
    return None


def _central_versions(start: Path, ctx: Context, result: DetectResult) -> dict[str, str]:
    """PackageVersion entries from the nearest Directory.Packages.props."""
    for d in dirs_up(start, ctx.root):
        file = d / CENTRAL
        if not file.is_file():
            continue
        try:
            root = ET.fromstring(file.read_bytes())
        except ET.ParseError:
            result.unrecognised.append(Unrecognised(rel(file, ctx), f"couldn't parse {CENTRAL}"))
            return {}
        found: dict[str, str] = {}
        for item in root.iter():
            if _local(item.tag) == "PackageVersion" and item.get("Include"):
                version = item.get("Version") or _child_text(item, "Version")
                if version:
                    found[item.get("Include")] = version
        return found
    return {}


def _props_chain(start: Path, root: Path) -> list[Path]:
    """Directory.Build.props files from start up to root, nearest first."""
    return [d / PROPS for d in dirs_up(start, root) if (d / PROPS).is_file()]


def _resolve(value: str, props: dict[str, str], depth: int = 0) -> str:
    if depth > 5:
        return value
    resolved = _PROP_REF.sub(lambda m: props.get(m.group(1), m.group(0)), value)
    return resolved if resolved == value else _resolve(resolved, props, depth + 1)


def _local(tag) -> str:
    return tag.split("}")[-1] if isinstance(tag, str) else ""
