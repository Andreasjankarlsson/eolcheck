"""Command-line entry point: eolchecker <folder>."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich.console import Console

from .api import ApiUnavailable, EolClient
from .detectors import Context
from .report import render
from .rows import build_rows
from .scan import scan


def main(argv: list[str] | None = None, client=None, detectors=None) -> int:
    parser = argparse.ArgumentParser(
        prog="eolchecker",
        description="Check whether the major frameworks in a repo are past end-of-life.",
    )
    parser.add_argument("path", help="folder of a cloned repo")
    parser.add_argument("--no-maven", action="store_true",
                        help="don't run Maven to resolve versions inherited from parent poms")
    args = parser.parse_args(argv)

    root = Path(args.path).expanduser()
    if not root.is_dir():
        print(f"Path not found: {args.path}", file=sys.stderr)
        return 2
    root = root.resolve()

    result = scan(root, Context(root, use_maven=not args.no_maven), detectors)
    console = Console(width=None if sys.stdout.isatty() else 200)
    if not result.findings and not result.unrecognised:
        console.print(f"No supported frameworks found in {root}")
        return 0

    try:
        rows = build_rows(result.findings, client or EolClient())
    except ApiUnavailable as exc:
        print(f"Couldn't fetch end-of-life dates from endoflife.date: {exc}", file=sys.stderr)
        return 1

    render(root.name, rows, result.unrecognised, console)
    return 0


if __name__ == "__main__":
    sys.exit(main())
