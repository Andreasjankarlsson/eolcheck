"""Turn findings and dependencies into table rows using endoflife.date data."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .api import Release
from .catalog import PurlIndex
from .models import COMPONENTS, Dependency, Finding
from .versions import cycle_candidates

DASH = "—"
_ORDER = {name: i for i, name in enumerate(COMPONENTS)}


@dataclass(frozen=True)
class Row:
    component: str
    dependencies: tuple[str, ...]
    version: str
    found_in: str
    end_of_support: str
    latest: str
    status: str


def _match(version: str, releases: list[Release]) -> Release | None:
    by_name = {r.name: r for r in releases}
    for candidate in cycle_candidates(version):
        if candidate in by_name:
            return by_name[candidate]
    return None


def _newest_latest(releases: list[Release]) -> str:
    """The highest version across all cycles (not the cycle released last: maintenance
    branches such as Log4j 2.12 keep getting releases after newer cycles)."""
    if not releases:
        return DASH
    return max((_tidy(r.latest or r.name) for r in releases), key=_vkey)


def _tidy(version: str) -> str:
    """'27.0.1.0.2+1' -> '27.0.1': drop build metadata and anything past major.minor.patch."""
    core = version.split("+")[0]
    if re.fullmatch(r"\d+(?:\.\d+)*", core):
        return ".".join(core.split(".")[:3])
    return version


def _vkey(version: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", version))


def _group_dependencies(
    dependencies: list[Dependency], index: PurlIndex
) -> dict[tuple[Path, str], tuple[str, list[Dependency]]]:
    """(source, product) -> (component, dependencies that belong to it)."""
    groups: dict[tuple[Path, str], tuple[str, list[Dependency]]] = {}
    for d in dependencies:
        for m in index.resolve(d.key):
            groups.setdefault((d.source, m.product), (m.component, []))[1].append(d)
    return groups


def _make_row(component: str, product: str, source: Path, origin: str,
              versions: list[tuple[str, str]], deps: list[Dependency], via_maven: bool,
              index: PurlIndex) -> Row | None:
    """versions: (normalised, display) pairs; deps: every dependency in the row."""
    if not versions:
        return None
    ordered = sorted(versions, key=lambda v: _vkey(v[0]))
    lowest_norm, lowest_display = ordered[0]
    others = []
    for _, display in ordered[1:]:
        if display != lowest_display and display not in others:
            others.append(display)
    shown = lowest_display + (f" (also {', '.join(others)})" if others else "")

    names = [n for n in sorted({d.name for d in deps}) if n != origin]
    if origin:
        names.insert(0, origin)

    releases = index.releases(product)
    latest = _newest_latest(releases) if releases else DASH
    if releases is None:
        status, eos = "not tracked", DASH
    else:
        match = _match(lowest_norm, releases)
        if match is None:
            status, eos = "unknown version", DASH
        elif match.is_eol:
            status, eos = "END OF LIFE", match.eol_from or DASH
        elif match.eol_from is None:
            status, eos = "no EOL date", DASH
        else:
            status, eos = "supported", match.eol_from
    found_in = source.as_posix() + (" (via Maven)" if via_maven else "")
    return Row(component, tuple(names), shown, found_in, eos, latest, status)


def build_rows(findings: list[Finding], dependencies: list[Dependency], index: PurlIndex) -> list[Row]:
    groups = _group_dependencies(dependencies, index)
    finding_count: dict[tuple[Path, str], int] = {}
    for f in findings:
        finding_count[(f.source, f.product)] = finding_count.get((f.source, f.product), 0) + 1

    rows: list[Row | None] = []
    merged: set[tuple[Path, str]] = set()
    for f in findings:
        key = (f.source, f.product)
        deps: list[Dependency] = []
        if finding_count[key] == 1 and key in groups:
            deps = groups[key][1]
            merged.add(key)
        versioned = [d for d in deps if d.version is not None]
        rows.append(_make_row(
            f.component, f.product, f.source, f.origin,
            [(f.version, f.display)] + [(d.version, d.display or d.version) for d in versioned],
            deps, f.via_maven or any(d.via_maven for d in versioned), index))
    for key, (component, deps) in groups.items():
        if key in merged:
            continue
        versioned = [d for d in deps if d.version is not None]
        rows.append(_make_row(
            component, key[1], key[0], "",
            [(d.version, d.display or d.version) for d in versioned],
            deps, any(d.via_maven for d in versioned), index))

    result = [r for r in rows if r is not None]
    result.sort(key=lambda r: (r.found_in, _ORDER.get(r.component, 99), r.component.casefold(), r.component))
    return result


def untracked_by_file(dependencies: list[Dependency], index: PurlIndex) -> dict[Path, list[str]]:
    found: dict[Path, set[str]] = {}
    for d in dependencies:
        if not index.resolve(d.key):
            found.setdefault(d.source, set()).add(d.name)
    return {source: sorted(names) for source, names in found.items()}
