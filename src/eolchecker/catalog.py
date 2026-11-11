"""The endoflife.date catalogue: products, their release cycles and the packages they ship as."""
from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import unquote

from .api import ApiUnavailable, Release
from .models import COMPONENTS, OVERRIDES

# Dependency keys ("<ecosystem>:<name>") that endoflife.date lists for a product but
# whose versions do not follow that product's release cycles (separately versioned
# sub-projects). They are never indexed.
#
# Checked against the live /products/full (489 products): no purl is claimed by more
# than one product, and none of the npm/maven/composer/nuget purls has an empty name
# or a qualifier/subpath/version part. All 15 COMPONENTS slugs exist. Flagged:
# - spring-cloud: only spring-cloud-dependencies carries the calendar release train
#   (2025.1, 2025.0, ...); commons, config, gateway and netflix are versioned 3.x/4.x.
# - apache-hadoop: hadoop-core is the abandoned 1.x artifact, not the 3.x cycles.
EXCLUDED_PURLS: frozenset[str] = frozenset({
    "maven:org.springframework.cloud/spring-cloud-commons",
    "maven:org.springframework.cloud/spring-cloud-config",
    "maven:org.springframework.cloud/spring-cloud-gateway",
    "maven:org.springframework.cloud/spring-cloud-netflix",
    "maven:org.apache.hadoop/hadoop-core",
})

_ECOSYSTEMS = frozenset({"npm", "maven", "composer", "nuget"})


@dataclass(frozen=True)
class Product:
    slug: str
    label: str
    releases: tuple[Release, ...]
    purls: tuple[str, ...]


@dataclass(frozen=True)
class Match:
    component: str
    product: str


def parse_release(raw: dict) -> Release:
    return Release(
        name=raw["name"],
        release_date=raw.get("releaseDate") or "",
        is_eol=bool(raw.get("isEol")),
        eol_from=raw.get("eolFrom"),
        latest=(raw.get("latest") or {}).get("name"),
    )


def parse_products(body: bytes) -> list[Product]:
    try:
        result = json.loads(body)["result"]
        return [
            Product(
                slug=p["name"],
                label=p.get("label") or p["name"],
                releases=tuple(parse_release(r) for r in p["releases"]),
                purls=tuple(
                    i["id"] for i in p.get("identifiers") or [] if i.get("type") == "purl"
                ),
            )
            for p in result
        ]
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ApiUnavailable("unexpected response for products/full") from exc


def purl_key(purl: str) -> str | None:
    """Dependency key for a package URL, or None for ecosystems we don't scan."""
    if not purl.startswith("pkg:"):
        return None
    rest = purl[4:].split("#", 1)[0].split("?", 1)[0]
    ecosystem, _, name = rest.partition("/")
    if ecosystem not in _ECOSYSTEMS or not name:
        return None
    # The version follows the name, which is the last path segment, so an '@' there starts the
    # version, while one in an earlier segment is an npm scope (written as @ or %40).
    namespace, slash, last = name.rpartition("/")
    last = last.split("@", 1)[0]
    if not last:
        return None
    return dep_key(ecosystem, unquote(namespace + slash + last))


def dep_key(ecosystem: str, name: str) -> str:
    return f"{ecosystem}:{name}".lower()


class PurlIndex:
    """Maps dependency keys to the products they belong to, and products to releases."""

    def __init__(self, products: Iterable[Product] = ()):
        excluded = EXCLUDED_PURLS
        self._releases: dict[str, list[Release]] = {}
        self._by_key: dict[str, list[Match]] = {}
        for p in sorted(products, key=lambda p: p.slug):
            self._releases[p.slug] = list(p.releases)
            for purl in p.purls:
                key = purl_key(purl)
                if key is None or key in excluded:
                    continue
                matches = self._by_key.setdefault(key, [])
                match = Match(p.label, p.slug)
                if match not in matches:
                    matches.append(match)

    def resolve(self, key: str) -> list[Match]:
        if key in OVERRIDES:
            component = OVERRIDES[key]
            return [Match(component, COMPONENTS[component])]
        return list(self._by_key.get(key, []))

    def releases(self, slug: str) -> list[Release] | None:
        found = self._releases.get(slug)
        return None if found is None else list(found)
