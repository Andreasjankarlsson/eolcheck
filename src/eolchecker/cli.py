"""Command-line entry point: eolchecker <folder>."""
from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path

from rich.console import Console

from .catalogue import ApiUnavailable, Catalogue, load_catalogue
from .detectors import Context
from .report import render
from .rows import SbomRow, build_report
from .sbom import write_sbom
from .scan import scan


def main(argv: list[str] | None = None, catalogue: Callable[[], Catalogue] | None = None,
         detectors=None) -> int:
    parser = argparse.ArgumentParser(
        prog="eolchecker",
        description="Check whether a repo's dependencies are past end-of-life.",
    )
    parser.add_argument("path", help="folder of a cloned repo")
    parser.add_argument("--no-maven", action="store_true",
                        help="don't run Maven to resolve versions inherited from parent poms")
    parser.add_argument("--sbom", metavar="FILE",
                        help="also write every detected dependency to FILE (.csv or .md)")
    args = parser.parse_args(argv)

    sbom_path = Path(args.sbom).expanduser() if args.sbom else None
    if sbom_path is not None and sbom_path.suffix.lower() not in (".csv", ".md"):
        print("--sbom file must end in .csv or .md", file=sys.stderr)
        return 2

    root = Path(args.path).expanduser()
    if not root.exists():
        print(f"Path not found: {args.path}", file=sys.stderr)
        return 2
    if not root.is_dir():
        print(f"Not a folder: {args.path}", file=sys.stderr)
        return 2
    root = root.resolve()

    result = scan(root, Context(root, use_maven=not args.no_maven), detectors)
    console = Console(width=None if sys.stdout.isatty() else 200)
    if not result.findings and not result.dependencies and not result.unrecognised:
        console.print(f"No dependencies found in {root}")
        return _write_sbom(sbom_path, [], console)

    try:
        cat = (catalogue or load_catalogue)()
    except ApiUnavailable as exc:
        print(f"Couldn't fetch end-of-life dates from endoflife.date: {exc}", file=sys.stderr)
        return 1

    report = build_report(result, cat)
    render(root.name, report.rows, report.unrecognised, console)
    return _write_sbom(sbom_path, report.sbom, console)


def _write_sbom(path: Path | None, rows: list[SbomRow], console: Console) -> int:
    """Write the SBOM if one was asked for; 1 if the file can't be written."""
    if path is None:
        return 0
    try:
        write_sbom(path, rows)
    except OSError as exc:
        print(f"Couldn't write {path}: {exc.strerror or exc}", file=sys.stderr)
        return 1
    console.print(f"SBOM written to {path}", soft_wrap=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
