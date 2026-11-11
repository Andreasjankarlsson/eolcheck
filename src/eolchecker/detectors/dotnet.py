""".NET and .NET Framework from project files, Directory.Build.props and global.json."""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from ..models import DetectResult, Unrecognised, finding
from ..versions import normalise
from . import Context
from ._util import dirs_up, parse_error, read_text, rel

PROJECT_SUFFIXES = (".csproj", ".fsproj", ".vbproj")
PROPS = "Directory.Build.props"
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
        return path.suffix in PROJECT_SUFFIXES or path.name == "global.json"

    def detect(self, path: Path, ctx: Context) -> DetectResult:
        if path.name == "global.json":
            return self._global_json(path, ctx)
        try:
            project_props = _properties(path)
        except ET.ParseError:
            return parse_error(path, ctx)

        props: dict[str, str] = {}
        for props_file in reversed(_props_chain(path.parent, ctx.root)):
            try:
                props.update(_properties(props_file))
            except ET.ParseError:
                continue
        props.update(project_props)

        raw = props.get("TargetFrameworks") or props.get("TargetFramework") or props.get("TargetFrameworkVersion")
        source = rel(path, ctx)
        if not raw:
            return DetectResult(unrecognised=[Unrecognised(source, NO_TARGET)])
        raw = _resolve(raw, props)

        result = DetectResult()
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
