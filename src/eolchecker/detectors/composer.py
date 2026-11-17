"""Every Composer dependency, plus the PHP runtime, from composer.json / composer.lock."""
from __future__ import annotations

import json
from pathlib import Path

from ..models import DetectResult, Dependency, finding
from ..versions import is_range, lowest, normalise
from . import Context
from ._util import gap, parse_error, read_text, rel


class ComposerDetector:
    def applies_to(self, path: Path) -> bool:
        return path.name == "composer.json"

    def detect(self, path: Path, ctx: Context) -> DetectResult:
        try:
            data = json.loads(read_text(path))
        except ValueError:
            return parse_error(path, ctx)
        if not isinstance(data, dict):
            return parse_error(path, ctx)

        result = DetectResult()
        source = rel(path, ctx)
        require = data.get("require") if isinstance(data.get("require"), dict) else {}
        locked = _locked_versions(path.parent / "composer.lock")

        platform = ((data.get("config") or {}).get("platform") or {}).get("php")
        php = platform if isinstance(platform, str) else require.get("php")
        if isinstance(php, str):
            _add(result, "PHP", php, None, path, ctx, source)

        require_dev = data.get("require-dev") if isinstance(data.get("require-dev"), dict) else {}
        declared_all: dict[str, str] = {}
        for section in (require, require_dev):
            for name, declared in section.items():
                if "/" in name and isinstance(declared, str):
                    declared_all.setdefault(name, declared)
        for name, declared in declared_all.items():
            result.dependencies.append(_dependency(name, declared, locked.get(name), source))
        return result


def _dependency(name: str, declared: str, locked: str | None, source: Path) -> Dependency:
    if locked:
        return Dependency("Composer", name, locked, locked, source)
    version = lowest(declared)
    if version is None:
        return Dependency("Composer", name, None, declared, source, missing=f"'{declared}' isn't a version")
    return Dependency("Composer", name, version, declared if is_range(declared) else version, source)


def _add(result: DetectResult, component: str, declared: str, locked: str | None,
         path: Path, ctx: Context, source: Path) -> None:
    if locked:
        result.findings.append(finding(component, locked, locked, source))
        return
    version = lowest(declared)
    if version is None:
        result.unrecognised.append(gap(path, ctx, component))
        return
    result.findings.append(finding(component, version, declared if is_range(declared) else version, source))


def _locked_versions(lock: Path) -> dict[str, str]:
    if not lock.is_file():
        return {}
    try:
        data = json.loads(read_text(lock))
    except ValueError:
        return {}
    out: dict[str, str] = {}
    for section in ("packages", "packages-dev"):
        for pkg in data.get(section) or []:
            if isinstance(pkg, dict) and isinstance(pkg.get("version"), str):
                v = normalise(pkg["version"])
                if v:
                    out.setdefault(pkg.get("name", ""), v)
    return out
