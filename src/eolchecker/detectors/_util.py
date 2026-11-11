"""Small helpers shared by detectors."""
from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from ..catalog import PurlIndex
from ..models import DetectResult, Dependency, Unrecognised
from . import Context


def rel(path: Path, ctx: Context) -> Path:
    return path.relative_to(ctx.root)


def read_text(path: Path) -> str:
    """Read a text file, tolerating a UTF-8 byte order mark."""
    return path.read_text(encoding="utf-8-sig")


def parse_error(path: Path, ctx: Context) -> DetectResult:
    return DetectResult(unrecognised=[Unrecognised(rel(path, ctx), f"couldn't parse {path.name}")])


def gap(path: Path, ctx: Context, component: str) -> Unrecognised:
    return Unrecognised(rel(path, ctx), f"couldn't read the {component} version")


def dirs_up(start: Path, root: Path) -> Iterable[Path]:
    """start, its parent, ... up to and including root."""
    current = start
    while True:
        yield current
        if current == root or root not in current.parents:
            return
        current = current.parent


def gaps_for(dependencies: list[Dependency], index: PurlIndex, path: Path, ctx: Context) -> list[Unrecognised]:
    """One gap per tracked product whose version could not be read from any of its packages in this file."""
    covered = {m.product for d in dependencies if d.version for m in index.resolve(d.key)}
    gaps: dict[str, Unrecognised] = {}
    for dep in dependencies:
        if dep.version:
            continue
        matches = index.resolve(dep.key)
        if matches and not any(m.product in covered for m in matches):
            gaps.setdefault(matches[0].component, gap(path, ctx, matches[0].component))
    return list(gaps.values())
