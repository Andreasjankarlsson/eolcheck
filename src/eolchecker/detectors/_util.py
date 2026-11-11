"""Small helpers shared by detectors."""
from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from ..models import DetectResult, Unrecognised
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
