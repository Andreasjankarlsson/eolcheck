"""Angular, AngularJS, React, Next.js and Node.js from package.json and friends."""
from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from ..models import DetectResult, finding
from ..versions import is_range, lowest, normalise
from . import Context
from ._util import dirs_up, gap, parse_error, read_text, rel

PACKAGES = {
    "@angular/core": "Angular",
    "angular": "AngularJS",
    "react": "React",
    "next": "Next.js",
}
LOCK_FILES = ("package-lock.json", "yarn.lock", "pnpm-lock.yaml")
DEP_SECTIONS = ("dependencies", "devDependencies", "peerDependencies")


class NpmDetector:
    def applies_to(self, path: Path) -> bool:
        return path.name in ("package.json", ".nvmrc", ".node-version")

    def detect(self, path: Path, ctx: Context) -> DetectResult:
        if path.name == "package.json":
            return self._package_json(path, ctx)
        return self._node_version_file(path, ctx)

    def _node_version_file(self, path: Path, ctx: Context) -> DetectResult:
        lines = read_text(path).strip().splitlines()
        first = lines[0].strip() if lines else ""
        version = normalise(first) if re.match(r"^[vV]?\d", first) else None
        if version is None:
            return DetectResult(unrecognised=[gap(path, ctx, "Node.js")])
        return DetectResult(findings=[finding("Node.js", version, version, rel(path, ctx))])

    def _package_json(self, path: Path, ctx: Context) -> DetectResult:
        try:
            data = json.loads(read_text(path))
        except ValueError:
            return parse_error(path, ctx)
        if not isinstance(data, dict):
            return parse_error(path, ctx)

        result = DetectResult()
        source = rel(path, ctx)
        lock = _Lock.find(path.parent, ctx.root)
        for name, component in PACKAGES.items():
            declared = _declared(data, name)
            if declared is None:
                continue
            locked = lock.version(name, declared, path.parent) if lock else None
            if locked:
                result.findings.append(finding(component, locked, locked, source))
                continue
            version = lowest(declared)
            if version is None:
                result.unrecognised.append(gap(path, ctx, component))
                continue
            display = declared if is_range(declared) else version
            result.findings.append(finding(component, version, display, source))

        engines = data.get("engines")
        node = engines.get("node") if isinstance(engines, dict) else None
        if isinstance(node, str):
            version = lowest(node)
            if version is None:
                result.unrecognised.append(gap(path, ctx, "Node.js"))
            else:
                result.findings.append(finding("Node.js", version, node if is_range(node) else version, source))
        return result


def _declared(data: dict, name: str) -> str | None:
    for section in DEP_SECTIONS:
        deps = data.get(section)
        if isinstance(deps, dict) and isinstance(deps.get(name), str):
            return deps[name]
    return None


class _Lock:
    """The nearest lock file, read lazily, with one lookup method per format."""

    def __init__(self, path: Path):
        self.path = path
        self._data = None

    @classmethod
    def find(cls, start: Path, root: Path) -> _Lock | None:
        for d in dirs_up(start, root):
            for name in LOCK_FILES:
                if (d / name).is_file():
                    return cls(d / name)
        return None

    def version(self, name: str, declared: str, pkg_dir: Path) -> str | None:
        try:
            if self.path.name == "package-lock.json":
                raw = self._npm(name, pkg_dir)
            elif self.path.name == "yarn.lock":
                raw = self._yarn(name, declared)
            else:
                raw = self._pnpm(name, pkg_dir)
        except (ValueError, yaml.YAMLError, AttributeError, TypeError):
            return None
        return normalise(raw) if isinstance(raw, str) else None

    def _load_json(self):
        if self._data is None:
            self._data = json.loads(read_text(self.path))
        return self._data

    def _npm(self, name: str, pkg_dir: Path) -> str | None:
        data = self._load_json()
        packages = data.get("packages") or {}
        sub = pkg_dir.relative_to(self.path.parent).as_posix()
        if sub != ".":
            # A lock file higher up only covers this package if it lists it as a workspace member.
            if sub not in packages:
                return None
            keys = [f"{sub}/node_modules/{name}", f"node_modules/{name}"]
        else:
            keys = [f"node_modules/{name}"]
        for key in keys:
            if key in packages:
                return packages[key].get("version")
        if sub != ".":
            return None
        dep = (data.get("dependencies") or {}).get(name)
        return dep.get("version") if isinstance(dep, dict) else None

    def _yarn(self, name: str, declared: str) -> str | None:
        wanted = {f"{name}@{declared}", f"{name}@npm:{declared}"}
        in_block = False
        for line in read_text(self.path).splitlines():
            if line and not line[0].isspace():
                entries = {e.strip().strip('"') for e in line.rstrip(":").split(",")}
                in_block = bool(entries & wanted)
            elif in_block:
                m = re.match(r'^\s+version:?\s+"?([^"\s]+)"?', line)
                if m:
                    return m.group(1)
        return None

    def _pnpm(self, name: str, pkg_dir: Path) -> str | None:
        if self._data is None:
            self._data = yaml.safe_load(read_text(self.path)) or {}
        data = self._data
        sub = pkg_dir.relative_to(self.path.parent).as_posix()
        importer = (data.get("importers") or {}).get(sub)
        if importer is None and sub == ".":
            importer = data
        if not isinstance(importer, dict):
            return None
        for section in DEP_SECTIONS:
            entry = (importer.get(section) or {}).get(name)
            if isinstance(entry, dict):
                entry = entry.get("version")
            if isinstance(entry, str):
                return entry.split("(")[0]
        return None
