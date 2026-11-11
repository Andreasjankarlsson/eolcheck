"""Print the results as a table."""
from __future__ import annotations

import csv
from pathlib import Path

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


def render(repo_name: str, rows: list[Row], unrecognised: list[Unrecognised], console: Console,
           untracked: dict[Path, list[str]] | None = None) -> None:
    console.print()
    console.print(f"[bold]{escape(repo_name)}[/bold]")
    if rows:
        table = Table(box=None, padding=(0, 2), header_style="bold")
        for col in ["Component", "Dependencies", "Version", "Found in", "End of support", "Latest", "Status"]:
            if col == "Dependencies":
                table.add_column(col, no_wrap=False, overflow="fold")
            elif col == "Found in":
                table.add_column(col, overflow="fold")
            else:
                table.add_column(col, no_wrap=True, overflow="ignore")
        for r in rows:
            style = STATUS_STYLE.get(r.status, "")
            table.add_row(r.component, escape(", ".join(r.dependencies)), r.version, r.found_in, r.end_of_support, r.latest,
                          f"[{style}]{escape(r.status)}[/{style}]" if style else escape(r.status))
        console.print(table)
    if unrecognised:
        console.print()
        console.print("Not recognised:")
        for u in sorted(unrecognised, key=lambda u: str(u.source)):
            console.print(f"  {escape(str(u.source))}: {escape(u.reason)}", soft_wrap=True)
    if untracked:
        console.print()
        console.print("Not on endoflife.date:")
        for path in sorted(untracked, key=str):
            console.print(f"  {escape(str(path))}: {escape(', '.join(untracked[path]))}", soft_wrap=True)
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
        for u in sorted(unrecognised, key=lambda u: str(u.source)):
            writer.writerow(["", u.reason, "", str(u.source), "", "", "not recognised"])
        for file in sorted(untracked or {}, key=str):
            writer.writerow(["", "; ".join(untracked[file]), "", str(file), "", "", "not tracked"])
