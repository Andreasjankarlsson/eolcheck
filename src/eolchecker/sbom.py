"""Render SBOM rows as CSV or a Markdown table."""
from __future__ import annotations

import csv
import io
from dataclasses import astuple
from pathlib import Path

from .rows import SbomRow

HEADER = ["Ecosystem", "Name", "Version", "Found in", "Product", "End of support", "Status"]


def to_csv(rows: list[SbomRow]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(HEADER)
    for row in rows:
        writer.writerow(astuple(row))
    return buf.getvalue()


def _md_line(cells) -> str:
    return "| " + " | ".join(str(c).replace("|", "\\|") for c in cells) + " |"


def to_markdown(rows: list[SbomRow]) -> str:
    lines = [_md_line(HEADER), "|" + "---|" * len(HEADER)]
    lines.extend(_md_line(astuple(row)) for row in rows)
    return "\n".join(lines) + "\n"


def write_sbom(path: Path, rows: list[SbomRow]) -> None:
    """Write the SBOM; the format follows the file suffix (.csv or .md)."""
    suffix = path.suffix.lower()
    if suffix == ".csv":
        text = to_csv(rows)
    elif suffix == ".md":
        text = to_markdown(rows)
    else:
        raise ValueError(f"Unsupported SBOM file type {path.suffix!r}; use .csv or .md")
    path.write_text(text, encoding="utf-8")
