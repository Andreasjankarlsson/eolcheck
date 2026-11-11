"""NuGet packages from PackageReference items (with central package management) and packages.config."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from ..catalog import dep_key
from ..models import DetectResult, Dependency, Unrecognised
from ..versions import lowest
from . import Context
from ._util import dirs_up, gaps_for, parse_error, rel
from .dotnet import PROJECT_SUFFIXES, _local

CENTRAL = "Directory.Packages.props"
PACKAGES_CONFIG = "packages.config"


class NugetDetector:
    def __init__(self) -> None:
        # Directory.Packages.props already read in the current scan (one Context per scan):
        # props path -> its versions, or None if it couldn't be parsed.
        self._ctx: Context | None = None
        self._central: dict[Path, dict[str, str] | None] = {}

    def _central_versions(self, start: Path, ctx: Context, result: DetectResult) -> dict[str, str]:
        """PackageVersion entries (lowercased id -> version) from the nearest Directory.Packages.props."""
        if ctx is not self._ctx:
            self._ctx, self._central = ctx, {}
        props = next((d / CENTRAL for d in dirs_up(start, ctx.root) if (d / CENTRAL).is_file()), None)
        if props is None:
            return {}
        if props not in self._central:
            self._central[props] = _read_central(props)
        versions = self._central[props]
        if versions is None:
            result.unrecognised.append(Unrecognised(rel(props, ctx), f"couldn't parse {CENTRAL}"))
            return {}
        return versions

    def applies_to(self, path: Path) -> bool:
        return path.suffix in PROJECT_SUFFIXES or path.name == PACKAGES_CONFIG

    def detect(self, path: Path, ctx: Context) -> DetectResult:
        try:
            # Bytes, so the XML parser honours the file's own encoding.
            root = ET.fromstring(path.read_bytes())
        except ET.ParseError:
            return parse_error(path, ctx)

        result = DetectResult()
        source = rel(path, ctx)
        if path.name == PACKAGES_CONFIG:
            declared = [(e.get("id"), e.get("version")) for e in root.iter() if _local(e.tag) == "package"]
        else:
            central = self._central_versions(path.parent, ctx, result)
            declared = []
            for item in root.iter():
                if _local(item.tag) != "PackageReference" or item.get("Include") is None:
                    continue
                name = item.get("Include")
                version = (_value(item, "VersionOverride") or _value(item, "Version")
                           or central.get(name.lower()))
                declared.append((name, version))

        for name, version in declared:
            if name:
                result.dependencies.append(_dependency(name.strip(), version, source))
        result.unrecognised.extend(gaps_for(result.dependencies, ctx.index, path, ctx))
        return result


def _dependency(name: str, raw: str | None, source: Path) -> Dependency:
    key = dep_key("nuget", name)
    raw = raw.strip() if raw else None
    version = None if not raw or "$(" in raw else lowest(raw)
    if version is None:
        return Dependency(key, name, None, None, source)
    return Dependency(key, name, version, raw, source)


def _value(item: ET.Element, name: str) -> str | None:
    """An attribute, or else a child element's text, of a PackageReference/PackageVersion."""
    if (attr := item.get(name)) and attr.strip():
        return attr.strip()
    for child in item:
        if _local(child.tag) == name and child.text and child.text.strip():
            return child.text.strip()
    return None


def _read_central(props: Path) -> dict[str, str] | None:
    """PackageVersion entries (lowercased id -> version) of a Directory.Packages.props; None if it can't be parsed."""
    try:
        root = ET.fromstring(props.read_bytes())
    except ET.ParseError:
        return None
    out: dict[str, str] = {}
    for item in root.iter():
        if _local(item.tag) == "PackageVersion" and item.get("Include") and (v := _value(item, "Version")):
            out[item.get("Include").strip().lower()] = v
    return out
