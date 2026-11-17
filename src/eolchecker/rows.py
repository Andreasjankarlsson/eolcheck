"""Turn detector output into table rows, SBOM rows and "Not recognised" lines."""
from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .catalogue import Catalogue, Product, Release
from .matching import Matcher, os_from_tag
from .models import DetectResult, Unrecognised
from .versions import cycle_candidates

DASH = "—"


@dataclass(frozen=True)
class Row:
    component: str
    version: str
    found_in: str
    end_of_support: str
    latest: str
    status: str


@dataclass(frozen=True)
class SbomRow:
    ecosystem: str
    name: str
    version: str
    found_in: str
    product: str
    end_of_support: str
    status: str


@dataclass(frozen=True)
class Report:
    rows: list[Row]
    sbom: list[SbomRow]
    unrecognised: list[Unrecognised]


@dataclass(frozen=True)
class _Member:
    """One dependency or OS reading that belongs to a product in a file."""
    version: str | None
    display: str
    by_rule: bool
    via_maven: bool = False
    missing: str | None = None
    sbom: tuple[str, str] | None = None  # (ecosystem, name); None for an unreadable OS


def _match(version: str, releases: Sequence[Release]) -> Release | None:
    by_name = {r.name: r for r in releases}
    for candidate in cycle_candidates(version):
        if candidate in by_name:
            return by_name[candidate]
    return None


def _newest_latest(releases: Sequence[Release]) -> str:
    if not releases:
        return DASH
    newest = max(releases, key=lambda r: r.release_date)
    return _tidy(newest.latest or newest.name)


def _tidy(version: str) -> str:
    """'27.0.1.0.2+1' -> '27.0.1': drop build metadata and anything past major.minor.patch."""
    core = version.split("+")[0]
    if re.fullmatch(r"\d+(?:\.\d+)*", core):
        return ".".join(core.split(".")[:3])
    return version


def _status(version: str, product: Product | None) -> tuple[Release | None, str | None, str]:
    """The matched release, its end of support (None if none) and the status text."""
    release = _match(version, product.releases) if product else None
    if release is None:
        return None, None, "version not found"
    if release.is_eol:
        return release, release.eol_from, "END OF LIFE"
    if release.eol_from is None:
        return release, None, "no EOL date"
    return release, release.eol_from, "supported"


def _key(version: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", version))


def _found_in(source: Path, via_maven: bool) -> str:
    return str(source) + (" (via Maven)" if via_maven else "")


def _choose(members: list[_Member], product: Product) -> _Member | None:
    """The member whose version the product row shows (spec section 5)."""
    versioned = [m for m in members if m.version]
    if not versioned:
        return None
    exact = [m for m in versioned if not m.by_rule]
    if exact:
        return min(exact, key=lambda m: _key(m.version))
    names = {r.name for r in product.releases}
    cycles: dict[str, list[_Member]] = {}
    for m in versioned:
        cycle = next((c for c in cycle_candidates(m.version) if c in names), m.version)
        cycles.setdefault(cycle, []).append(m)
    best = min(cycles, key=lambda c: (-len(cycles[c]), _key(c)))
    return min(cycles[best], key=lambda m: _key(m.version))


def build_report(result: DetectResult, catalogue: Catalogue) -> Report:
    matcher = Matcher(catalogue)
    rows: list[Row] = []
    sbom: list[SbomRow] = []
    gaps: list[Unrecognised] = list(result.unrecognised)

    for f in result.findings:
        product = catalogue.product(f.product)
        _, eos, status = _status(f.version, product)
        latest = _newest_latest(product.releases) if product else DASH
        rows.append(Row(f.component, f.display, _found_in(f.source, f.via_maven), eos or DASH, latest, status))
        sbom.append(SbomRow("Runtime", f.component, f.display, str(f.source),
                            product.label if product else "", eos or "", status))

    groups: dict[tuple[str, Path], list[_Member]] = {}
    for dep in result.dependencies:
        match = matcher.match(dep)
        version, display = dep.version, dep.display
        if dep.ecosystem == "Docker" and dep.tag:
            reading = os_from_tag(dep.tag, catalogue)
            for hit in reading.hits:
                os_product = catalogue.product(hit.product)
                if os_product is None:
                    continue
                if match and hit.product == match.product:
                    if version is None:  # the image is the OS itself: one row, from the codename
                        version, display = hit.version, hit.display
                    continue
                groups.setdefault((hit.product, dep.source), []).append(
                    _Member(hit.version, hit.display, False, sbom=("Docker", os_product.label)))
            for slug, reason in reading.missing:
                if catalogue.product(slug) is not None:
                    groups.setdefault((slug, dep.source), []).append(_Member(None, "", False, missing=reason))
        if match is None:
            sbom.append(SbomRow(dep.ecosystem, dep.name, display, str(dep.source), "", "", ""))
            continue
        groups.setdefault((match.product, dep.source), []).append(_Member(
            version, display, match.by_rule, dep.via_maven,
            None if version else dep.missing, (dep.ecosystem, dep.name)))

    for (slug, source), members in groups.items():
        product = catalogue.product(slug)
        chosen = _choose(members, product)
        chosen_release = None
        if chosen is None:
            reason = next((m.missing for m in members if m.missing), None)
            text = f"couldn't read the {product.label} version" + (f" ({reason})" if reason else "")
            gaps.append(Unrecognised(source, text))
        else:
            chosen_release, eos, status = _status(chosen.version, product)
            rows.append(Row(product.label, chosen.display, _found_in(source, chosen.via_maven),
                            eos or DASH, _newest_latest(product.releases), status))
        for m in members:
            if m.sbom is None:
                continue
            eos, status = "", ""
            if m.version:
                release, own_eos, own_status = _status(m.version, product)
                # A Docker image matched by name is that product itself, so its own version always counts.
                if not m.by_rule or m.sbom[0] == "Docker" or (release is not None and release == chosen_release):
                    eos, status = own_eos or "", own_status
            sbom.append(SbomRow(m.sbom[0], m.sbom[1], m.display, str(source), product.label, eos, status))

    seen: dict[tuple[str, ...], SbomRow] = {}
    for s in sbom:
        # Runtimes and Docker images can repeat in one file with different versions (e.g. multi-stage builds).
        key = (s.ecosystem, s.name, s.found_in) + ((s.version,) if s.ecosystem in ("Runtime", "Docker") else ())
        seen.setdefault(key, s)
    rows.sort(key=lambda r: (r.found_in, r.component))
    return Report(
        rows=rows,
        sbom=sorted(seen.values(), key=lambda s: (s.found_in, s.ecosystem, s.name)),
        unrecognised=list(dict.fromkeys(gaps)),
    )
