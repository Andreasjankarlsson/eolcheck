"""Ask Maven itself for the effective pom, to fill in versions inherited from parents outside the repo."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

from ._util import dirs_up

TIMEOUT_SECONDS = 180

Runner = Callable[[list[str], Path], subprocess.CompletedProcess]


def run_subprocess(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=TIMEOUT_SECONDS)


def find_maven(pom: Path, root: Path) -> list[str] | None:
    """The nearest executable ./mvnw from the pom's folder up to the repo root, else mvn on PATH."""
    for d in dirs_up(pom.parent, root):
        wrapper = d / "mvnw"
        if wrapper.is_file() and os.access(wrapper, os.X_OK):
            return [str(wrapper)]
    return ["mvn"] if shutil.which("mvn") else None


def effective_pom(pom: Path, root: Path, runner: Runner = run_subprocess,
                  tmp_dir: Path | None = None) -> str | None:
    """The effective pom as text, or None if Maven is missing or fails."""
    maven = find_maven(pom, root)
    if maven is None:
        return None
    with tempfile.TemporaryDirectory(dir=tmp_dir) as tmp:
        out = Path(tmp) / "effective-pom.xml"
        cmd = maven + ["-q", "-B", "-N", "-f", str(pom), "help:effective-pom", f"-Doutput={out}"]
        try:
            proc = runner(cmd, pom.parent)
        except (OSError, subprocess.SubprocessError):
            return None
        if proc.returncode != 0 or not out.is_file():
            return None
        return out.read_text(encoding="utf-8")
