"""Detectors find framework versions in build files.

Each detector is small and self-contained: it says which files it reads
(`applies_to`) and returns what it found in one file (`detect`). Register new
detectors at the bottom of this module.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..models import DetectResult


@dataclass(frozen=True)
class Context:
    root: Path
    use_maven: bool = True


class Detector(Protocol):
    def applies_to(self, path: Path) -> bool: ...

    def detect(self, path: Path, ctx: Context) -> DetectResult: ...


DETECTORS: list[Detector] = []

from .composer import ComposerDetector  # noqa: E402
from .dotnet import DotnetDetector  # noqa: E402
from .npm import NpmDetector  # noqa: E402

DETECTORS.append(NpmDetector())
DETECTORS.append(ComposerDetector())
DETECTORS.append(DotnetDetector())
