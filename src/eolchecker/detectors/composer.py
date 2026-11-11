"""PHP, Laravel and Symfony from composer.json / composer.lock."""
from __future__ import annotations

import json
from pathlib import Path

from ..models import DetectResult, finding
from ..versions import is_range, lowest, normalise
from . import Context
from ._util import gap, parse_error, read_text, rel

# Component -> package names to look for, first match wins.
PACKAGES = {
    "Laravel": ("laravel/framework",),
    "Symfony": ("symfony/framework-bundle", "symfony/http-kernel"),
}


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

        for component, names in PACKAGES.items():
            for name in names:
                if isinstance(require.get(name), str):
                    _add(result, component, require[name], locked.get(name), path, ctx, source)
                    break
        return result


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
