"""Walk a folder and run detectors on each file."""
from __future__ import annotations

import os
from collections.abc import Iterator, Sequence
from pathlib import Path

from .detectors import DETECTORS, Context, Detector
from .models import DetectResult, Unrecognised

SKIP_DIRS = frozenset({".git", "node_modules", "vendor", "target", "build", "dist", "bin", "obj", ".idea", ".venv"})


def iter_files(root: Path) -> Iterator[Path]:
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            yield Path(dirpath) / name


def scan(root: Path, ctx: Context, detectors: Sequence[Detector] | None = None) -> DetectResult:
    detectors = DETECTORS if detectors is None else detectors
    result = DetectResult()
    for path in iter_files(root):
        for det in detectors:
            if not det.applies_to(path):
                continue
            try:
                result.extend(det.detect(path, ctx))
            except Exception:
                result.unrecognised.append(Unrecognised(path.relative_to(root), f"couldn't parse {path.name}"))
    return result
