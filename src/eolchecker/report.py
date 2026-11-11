"""Print the results as a table."""
from __future__ import annotations

import csv
from pathlib import Path

from rich.cells import cell_len
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from .models import Unrecognised
from .rows import DASH, Row

STATUS_STYLE = {
    "END OF LIFE": "bold red",
    "supported": "green",
    "no EOL date": "yellow",
    "unknown version": "dim",
    "not tracked": "dim",
}

CSV_HEADER = ["Component", "Dependencies", "Version", "Found in", "End of support", "Latest", "Status"]
COMPONENT, DEPENDENCIES, VERSION, FOUND_IN, END_OF_SUPPORT, LATEST, STATUS = range(len(CSV_HEADER))
_DEPENDENCIES_MIN = 18
_SQUEEZED = 4  # End of support / Latest when space is very short
_NARROW_GAP = "narrow gap"

# When the table is too wide, columns shrink in this order, each down to its floor:
# "token" is the longest word in the column (so it only wraps between words), a number is
# a width in characters. _NARROW_GAP drops the space between columns from two to one.
# Component and Status never shrink, and Found in never breaks inside a path.
_SHRINK = [
    (DEPENDENCIES, _DEPENDENCIES_MIN), (END_OF_SUPPORT, "token"), (LATEST, "token"),
    (VERSION, "token"), (FOUND_IN, "token"), _NARROW_GAP,
    (END_OF_SUPPORT, _SQUEEZED), (LATEST, _SQUEEZED), (DEPENDENCIES, 1),
]


def _cells(r: Row) -> list[str]:
    return [r.component, ", ".join(r.dependencies), r.version, r.found_in, r.end_of_support, r.latest, r.status]


def _layout(rows: list[list[str]], width: int) -> tuple[list[int], int]:
    """Content width per column and the gap between columns, so the table fits `width`."""
    columns = list(zip(CSV_HEADER, *rows))
    natural = [max(cell_len(c) for c in col) for col in columns]
    widths = list(natural)
    tokens = [max(cell_len(w) for c in col for w in c.split() or [""]) for col in columns]
    gap = 2
    for step in _SHRINK:
        excess = sum(widths) + gap * (len(CSV_HEADER) - 1) - width
        if excess <= 0:
            break
        if step == _NARROW_GAP:
            gap = 1
            continue
        col, floor = step
        floor = tokens[col] if floor == "token" else floor
        if widths[col] > floor:
            widths[col] = max(floor, widths[col] - excess)
    spare = width - sum(widths) - gap * (len(CSV_HEADER) - 1)
    if spare > 0:  # a step can overshoot; give the rest back to Dependencies
        widths[DEPENDENCIES] = min(natural[DEPENDENCIES], widths[DEPENDENCIES] + spare)
    return widths, gap


def render(repo_name: str, rows: list[Row], unrecognised: list[Unrecognised], console: Console,
           untracked: dict[Path, list[str]] | None = None) -> None:
    console.print()
    console.print(f"[bold]{escape(repo_name)}[/bold]")
    if rows:
        cells = [_cells(r) for r in rows]
        widths, gap = _layout(cells, console.width)
        # Right padding 1, left padding gap - 1: `gap` spaces between columns, none at the edges.
        table = Table(box=None, padding=(0, 1, 0, gap - 1), pad_edge=False, header_style="bold")
        for col, width in zip(CSV_HEADER, widths):
            table.add_column(col, width=width, overflow="fold")
        for r, row_cells in zip(rows, cells):
            style = STATUS_STYLE.get(r.status, "")
            status = escape(r.status)
            table.add_row(*[escape(c) for c in row_cells[:STATUS]],
                          f"[{style}]{status}[/{style}]" if style else status)
        console.print(table)
    if unrecognised:
        console.print()
        console.print("Not recognised:")
        for u in sorted(unrecognised, key=lambda u: u.source.as_posix()):
            console.print(f"  {escape(u.source.as_posix())}: {escape(u.reason)}", soft_wrap=True)
    if untracked:
        console.print()
        console.print("Not on endoflife.date:")
        for path in sorted(untracked, key=Path.as_posix):
            console.print(f"  {escape(path.as_posix())}: {escape(', '.join(untracked[path]))}", soft_wrap=True)
    console.print()


def write_csv(path: Path, rows: list[Row], unrecognised: list[Unrecognised],
              untracked: dict[Path, list[str]] | None = None) -> None:
    def cell(value: str) -> str:
        return "" if value == DASH else value

    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_HEADER)
        for r in rows:
            writer.writerow([r.component, "; ".join(r.dependencies), cell(r.version), cell(r.found_in),
                             cell(r.end_of_support), cell(r.latest), r.status])
        for u in sorted(unrecognised, key=lambda u: u.source.as_posix()):
            writer.writerow(["", u.reason, "", u.source.as_posix(), "", "", "not recognised"])
        for file in sorted(untracked or {}, key=Path.as_posix):
            writer.writerow(["", "; ".join(untracked[file]), "", file.as_posix(), "", "", "not tracked"])
