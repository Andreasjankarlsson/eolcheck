"""PHP, plus every package in composer.json (versions from composer.lock when present)."""
from __future__ import annotations

import json
from pathlib import Path

from ..catalog import dep_key
from ..models import DetectResult, Dependency, finding
from ..versions import is_range, lowest, normalise
from . import Context
from ._util import gap, gaps_for, parse_error, read_text, rel


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
            origin = "config.platform.php" if isinstance(platform, str) else "require.php"
            version = lowest(php)
            if version is None:
                result.unrecognised.append(gap(path, ctx, "PHP"))
            else:
                result.findings.append(finding("PHP", version, php if is_range(php) else version, source,
                                                origin=origin))

        for section in ("require", "require-dev"):
            packages = data.get(section)
            if not isinstance(packages, dict):
                continue
            for name, declared in packages.items():
                if "/" not in name or not isinstance(declared, str):
                    continue
                result.dependencies.append(_dependency(name, declared, locked.get(name), source))
        result.unrecognised.extend(gaps_for(result.dependencies, ctx.index, path, ctx))
        return result


def _dependency(name: str, declared: str, locked: str | None, source: Path) -> Dependency:
    key = dep_key("composer", name)
    if locked:
        return Dependency(key, name, locked, locked, source)
    version = lowest(declared)
    if version is None:
        return Dependency(key, name, None, None, source)
    return Dependency(key, name, version, declared if is_range(declared) else version, source)


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
