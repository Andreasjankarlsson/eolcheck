"""Print the results as a table."""
from __future__ import annotations

from rich.console import Console
from rich.markup import escape
from rich.table import Table

from .models import Unrecognised
from .rows import Row

STATUS_STYLE = {
    "END OF LIFE": "bold red",
    "supported": "green",
    "no EOL date": "yellow",
    "unknown": "dim",
    "unknown version": "dim",
    "not tracked": "dim",
}


def render(repo_name: str, rows: list[Row], unrecognised: list[Unrecognised], console: Console) -> None:
    console.print()
    console.print(f"[bold]{escape(repo_name)}[/bold]")
    if rows:
        table = Table(box=None, padding=(0, 2), header_style="bold")
        for col in ["Component", "Dependencies", "Version", "Found in", "End of support", "Latest", "Status"]:
            table.add_column(col, no_wrap=True)
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
    console.print()
