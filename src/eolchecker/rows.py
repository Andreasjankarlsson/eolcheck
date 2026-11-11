"""Turn findings into table rows using endoflife.date data."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .api import Release
from .models import COMPONENTS, Finding
from .versions import cycle_candidates

DASH = "—"
_ORDER = {name: i for i, name in enumerate(COMPONENTS)}


class ReleaseSource(Protocol):
    def releases(self, product: str) -> list[Release] | None: ...


@dataclass(frozen=True)
class Row:
    component: str
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
    if not releases:
        return DASH
    newest = max(releases, key=lambda r: r.release_date)
    return newest.latest or newest.name


def build_rows(findings: list[Finding], client: ReleaseSource) -> list[Row]:
    cache: dict[str, list[Release] | None] = {}
    rows = []
    for f in findings:
        if f.product not in cache:
            cache[f.product] = client.releases(f.product)
        releases = cache[f.product]
        found_in = str(f.source) + (" (via Maven)" if f.via_maven else "")
        latest = _newest_latest(releases) if releases else DASH
        match = _match(f.version, releases) if releases else None
        if match is None:
            status, eos = "unknown", DASH
        elif match.is_eol:
            status, eos = "END OF LIFE", match.eol_from or DASH
        elif match.eol_from is None:
            status, eos = "no EOL date", DASH
        else:
            status, eos = "supported", match.eol_from
        rows.append(Row(f.component, f.display, found_in, eos, latest, status))
    rows.sort(key=lambda r: (r.found_in, _ORDER.get(r.component, 99)))
    return rows
