"""Command-line entry point: eolchecker <folder>."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich.console import Console

from .api import ApiUnavailable, EolClient
from .cache import default_cache_dir, load_catalog
from .catalog import PurlIndex
from .detectors import Context
from .report import render, write_csv
from .rows import build_rows, untracked_by_file
from .scan import scan


def _warn(message: str) -> None:
    print(message, file=sys.stderr)


def main(argv: list[str] | None = None, client=None, detectors=None,
         cache_dir: Path | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="eolchecker",
        description="Check whether a repo's dependencies are past end-of-life.",
    )
    parser.add_argument("path", help="folder of a cloned repo")
    parser.add_argument("--no-maven", action="store_true",
                        help="don't run Maven to resolve versions inherited from parent poms")
    parser.add_argument("--show-untracked", action="store_true",
                        help="also list dependencies that endoflife.date doesn't track")
    parser.add_argument("--csv", metavar="FILE", help="also write the results to a CSV file")
    parser.add_argument("--refresh", action="store_true",
                        help="ignore the cached endoflife.date data and fetch it again")
    args = parser.parse_args(argv)

    root = Path(args.path).expanduser()
    if not root.exists():
        print(f"Path not found: {args.path}", file=sys.stderr)
        return 2
    if not root.is_dir():
        print(f"Not a folder: {args.path}", file=sys.stderr)
        return 2
    root = root.resolve()

    try:
        products = load_catalog(client or EolClient(), cache_dir or default_cache_dir(_warn),
                                refresh=args.refresh, warn=_warn)
    except ApiUnavailable as exc:
        print(f"Couldn't fetch end-of-life dates from endoflife.date: {exc}", file=sys.stderr)
        return 1
    index = PurlIndex(products)

    result = scan(root, Context(root, use_maven=not args.no_maven, index=index), detectors)
    rows = build_rows(result.findings, result.dependencies, index)
    untracked = untracked_by_file(result.dependencies, index) if args.show_untracked else None

    console = Console(width=None if sys.stdout.isatty() else 200)
    if not rows and not result.unrecognised:
        console.print(f"No tracked dependencies found in {root}")
        if untracked:
            render(root.name, rows, result.unrecognised, console, untracked)
    else:
        render(root.name, rows, result.unrecognised, console, untracked)

    if args.csv:
        try:
            write_csv(Path(args.csv), rows, result.unrecognised, untracked)
        except OSError as exc:
            print(f"Couldn't write {args.csv}: {exc.strerror or exc}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
