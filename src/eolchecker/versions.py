"""Helpers for making sense of version text found in build files."""
from __future__ import annotations

import re

_NUMERIC = re.compile(r"\d+(?:\.\d+)*")
_RANGE_MARKERS = re.compile(r"[\^~<>|*\s]|\.x\b|\.X\b|^x$")


def normalise(raw: str) -> str | None:
    """'v6.4.1' -> '6.4.1', '6.4.1.Final' -> '6.4.1', 'latest' -> None."""
    text = raw.strip().lstrip("vV")
    m = _NUMERIC.match(text)
    return m.group(0) if m else None


def is_range(raw: str) -> bool:
    return bool(_RANGE_MARKERS.search(raw.strip()))


def lowest(raw: str) -> str | None:
    """Lowest version a range allows; None when no version can be read."""
    text = raw.strip()
    if not text or ":" in text or "/" in text:
        return None
    best: tuple[int, ...] | None = None
    best_text: str | None = None
    for alt in re.split(r"\|\|?", text):
        if alt.strip().startswith("<"):
            continue  # only an upper limit ("<20"): says nothing about the lowest version
        m = _NUMERIC.search(alt)
        if not m:
            continue
        key = tuple(int(p) for p in m.group(0).split("."))
        if best is None or key < best:
            best, best_text = key, m.group(0)
    return best_text


def cycle_candidates(version: str) -> list[str]:
    """'4.7.2' -> ['4.7.2', '4.7', '4']."""
    parts = version.split(".")
    out: list[str] = []
    for i in range(len(parts), 0, -1):
        c = ".".join(parts[:i])
        if c not in out:
            out.append(c)
    return out
