"""Every dependency in package.json, plus Node.js from engines, .nvmrc and .node-version."""
from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from ..catalog import dep_key
from ..models import DetectResult, Dependency, finding
from ..versions import is_range, lowest, normalise
from . import Context
from ._util import dirs_up, gap, gaps_for, parse_error, read_text, rel

LOCK_FILES = ("package-lock.json", "yarn.lock", "pnpm-lock.yaml")
DEP_SECTIONS = ("dependencies", "devDependencies", "peerDependencies")


class NpmDetector:
    def __init__(self) -> None:
        # Lock files already read in the current scan (one Context per scan), so a root lock
        # shared by many workspaces is parsed once.
        self._ctx: Context | None = None
        self._locks: dict[Path, _Lock] = {}

    def _lock(self, start: Path, ctx: Context) -> _Lock | None:
        if ctx is not self._ctx:
            self._ctx, self._locks = ctx, {}
        path = _find_lock(start, ctx.root)
        if path is None:
            return None
        if path not in self._locks:
            self._locks[path] = _Lock(path)
        return self._locks[path]

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
        return DetectResult(findings=[finding("Node.js", version, version, rel(path, ctx), origin=path.name)])

    def _package_json(self, path: Path, ctx: Context) -> DetectResult:
        try:
            data = json.loads(read_text(path))
        except ValueError:
            return parse_error(path, ctx)
        if not isinstance(data, dict):
            return parse_error(path, ctx)

        result = DetectResult()
        source = rel(path, ctx)
        lock = self._lock(path.parent, ctx)
        for section in DEP_SECTIONS:
            deps = data.get(section)
            if not isinstance(deps, dict):
                continue
            for name, declared in deps.items():
                if not isinstance(declared, str):
                    continue
                result.dependencies.append(_dependency(name, declared, lock, path, source))
        result.unrecognised.extend(gaps_for(result.dependencies, ctx.index, path, ctx))

        engines = data.get("engines")
        node = engines.get("node") if isinstance(engines, dict) else None
        if isinstance(node, str):
            version = lowest(node)
            if version is None:
                result.unrecognised.append(gap(path, ctx, "Node.js"))
            else:
                result.findings.append(finding("Node.js", version, node if is_range(node) else version, source,
                                                origin="engines.node"))
        return result


def _dependency(name: str, declared: str, lock: _Lock | None, path: Path, source: Path) -> Dependency:
    key = dep_key("npm", name)
    locked = lock.version(name, declared, path.parent) if lock else None
    if locked:
        return Dependency(key, name, locked, locked, source)
    version = lowest(declared)
    if version is None:
        return Dependency(key, name, None, None, source)
    return Dependency(key, name, version, declared if is_range(declared) else version, source)


def _find_lock(start: Path, root: Path) -> Path | None:
    """The nearest lock file at or above `start`."""
    for d in dirs_up(start, root):
        for name in LOCK_FILES:
            if (d / name).is_file():
                return d / name
    return None


class _Lock:
    """A lock file, read once on first use, with one lookup method per format."""

    def __init__(self, path: Path):
        self.path = path
        self._data = None

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
        if self._data is None:
            self._data = _yarn_versions(read_text(self.path))
        for entry in (f"{name}@{declared}", f"{name}@npm:{declared}"):
            if entry in self._data:
                return self._data[entry]
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


def _yarn_versions(text: str) -> dict[str, str]:
    """yarn.lock (classic or berry) as entry ('react@^18.2.0', 'react@npm:^18.2.0') -> version."""
    versions: dict[str, str] = {}
    entries: set[str] = set()
    for line in text.splitlines():
        if line and not line[0].isspace():
            entries = {e.strip().strip('"') for e in line.rstrip(":").split(",")}
        elif entries:
            m = re.match(r'^\s+version:?\s+"?([^"\s]+)"?', line)
            if m:
                for entry in entries:
                    versions.setdefault(entry, m.group(1))
                entries = set()
    return versions
