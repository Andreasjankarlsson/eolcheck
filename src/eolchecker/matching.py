"""Match detected dependencies to endoflife.date products by package URL."""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import unquote

from .catalogue import Catalogue
from .models import Dependency

_DOCKER_HUBS = ("docker.io/", "index.docker.io/", "registry-1.docker.io/")


def normalise_purl(purl: str) -> str:
    """Canonical form: no version, no qualifiers (bar repository_url for docker/oci), decoded, lower-cased."""
    base, _, query = purl.partition("?")
    kept = ""
    if base.startswith(("pkg:docker/", "pkg:oci/")):
        for part in query.split("&"):
            if part.startswith("repository_url="):
                kept = "?" + part
    head, sep, last = base.rpartition("/")
    last = last.rsplit("@", 1)[0] if not last.startswith("@") else last
    path = unquote(head + sep + last)
    if path.startswith("pkg:maven/"):
        return path + kept.lower()
    return (path + kept).lower()


def _strip_hub(image: str) -> str:
    image = image.lower()
    for hub in _DOCKER_HUBS:
        if image.startswith(hub):
            return image[len(hub):]
    return image


def docker_purl(image: str) -> str:
    image = _strip_hub(image)
    parts = image.split("/")
    first = parts[0]
    if len(parts) > 1 and ("." in first or ":" in first or first == "localhost"):
        return f"pkg:oci/{parts[-1]}?repository_url={'/'.join(parts[:-1])}"
    if len(parts) == 1:
        image = "library/" + image
    return f"pkg:docker/{image}"


def is_official_image(image: str) -> bool:
    image = _strip_hub(image)
    if image.startswith("library/"):
        image = image[len("library/"):]
    return "/" not in image


def dependency_purl(dep: Dependency) -> str:
    if dep.ecosystem == "Docker":
        return docker_purl(dep.name)
    if dep.ecosystem == "Maven":
        group, _, artifact = dep.name.partition(":")
        return normalise_purl(f"pkg:maven/{group}/{artifact}")
    return f"pkg:{dep.ecosystem.lower()}/{dep.name.lower()}"


@dataclass(frozen=True)
class Match:
    product: str
    by_rule: bool


def _unique(claims: dict[str, set[str]]) -> dict[str, str]:
    return {key: next(iter(slugs)) for key, slugs in claims.items() if len(slugs) == 1}


class Matcher:
    def __init__(self, catalogue: Catalogue) -> None:
        exact: dict[str, str] = {}
        groups: dict[str, set[str]] = {}
        vendors: dict[str, set[str]] = {}
        names: dict[str, set[str]] = {}
        for product in catalogue.products():
            normalised = [normalise_purl(p) for p in product.purls]
            for purl in normalised:
                exact.setdefault(purl, product.name)
                if purl.startswith("pkg:maven/") and purl.count("/") >= 2:
                    groups.setdefault(purl.split("/")[1], set()).add(product.name)
            labels = {product.name.lower(), *(a.lower() for a in product.aliases)}
            for label in labels:
                names.setdefault(label, set()).add(product.name)
                if not any(p.startswith("pkg:composer/") for p in normalised):
                    vendors.setdefault(label, set()).add(product.name)
        self._exact = exact
        self._groups = _unique(groups)
        self._vendors = _unique(vendors)
        self._names = _unique(names)

    def match(self, dep: Dependency) -> Match | None:
        slug = self._exact.get(dependency_purl(dep))
        if slug:
            return Match(slug, False)
        slug = None
        if dep.ecosystem == "Maven":
            slug = self._groups.get(dep.name.partition(":")[0])
        elif dep.ecosystem == "Composer":
            slug = self._vendors.get(dep.name.lower().partition("/")[0])
        elif dep.ecosystem == "Docker" and is_official_image(dep.name):
            slug = self._names.get(_strip_hub(dep.name).removeprefix("library/"))
        return Match(slug, True) if slug else None
