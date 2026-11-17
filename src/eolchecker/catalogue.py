"""The full endoflife.date catalogue: download, on-disk cache and parsing."""
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

FULL_URL = "https://endoflife.date/api/v1/products/full"
MAX_AGE_SECONDS = 24 * 3600
_CACHE_NAME = "products-full.json"


class ApiUnavailable(Exception):
    """endoflife.date could not be reached or returned something unusable."""


@dataclass(frozen=True)
class Release:
    name: str
    release_date: str
    is_eol: bool
    eol_from: str | None
    latest: str | None
    codename: str | None = None


@dataclass(frozen=True)
class Product:
    name: str
    label: str
    aliases: tuple[str, ...]
    purls: tuple[str, ...]
    releases: tuple[Release, ...]


class Catalogue:
    def __init__(self, products: dict[str, Product]):
        self._products = products

    def product(self, slug: str) -> Product | None:
        return self._products.get(slug)

    def products(self) -> list[Product]:
        return list(self._products.values())


def _parse_release(raw: dict) -> Release:
    return Release(
        name=raw["name"],
        release_date=raw.get("releaseDate") or "",
        is_eol=bool(raw.get("isEol")),
        eol_from=raw.get("eolFrom"),
        latest=(raw.get("latest") or {}).get("name"),
        codename=raw.get("codename"),
    )


def _parse_product(raw: dict) -> Product:
    return Product(
        name=raw["name"],
        label=raw.get("label") or raw["name"],
        aliases=tuple(raw.get("aliases") or ()),
        purls=tuple(
            i["id"] for i in raw.get("identifiers") or () if i.get("type") == "purl"
        ),
        releases=tuple(_parse_release(r) for r in raw["releases"]),
    )


def parse_catalogue(data: dict) -> Catalogue:
    """Build a Catalogue from the `/products/full` payload."""
    try:
        products = [_parse_product(raw) for raw in data["result"]]
    except (KeyError, TypeError, AttributeError) as exc:
        raise ApiUnavailable("unexpected catalogue response") from exc
    return Catalogue({p.name: p for p in products})


def default_cache_file() -> Path:
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches"
    else:
        xdg = os.environ.get("XDG_CACHE_HOME")
        base = Path(xdg) if xdg else Path.home() / ".cache"
    return base / "eolchecker" / _CACHE_NAME


def _read_cache(path: Path) -> tuple[Catalogue, float] | None:
    """The cached catalogue and its mtime, or None if missing or unusable."""
    try:
        mtime = path.stat().st_mtime
        return parse_catalogue(json.loads(path.read_text())), mtime
    except (OSError, ValueError, ApiUnavailable):
        return None


def _download(http: httpx.Client | None) -> dict:
    client = http or httpx.Client(
        follow_redirects=True, timeout=30, headers={"User-Agent": "eolchecker/0.1"}
    )
    try:
        resp = client.get(FULL_URL)
        if resp.status_code != 200:
            raise ApiUnavailable(f"HTTP {resp.status_code} from endoflife.date")
        return resp.json()
    except httpx.HTTPError as exc:
        raise ApiUnavailable(str(exc) or type(exc).__name__) from exc
    except ValueError as exc:
        raise ApiUnavailable("endoflife.date returned invalid JSON") from exc


def _write_cache(path: Path, data: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))
    except OSError:
        pass


def _age(seconds: float) -> str:
    days = int(seconds // 86400)
    if days >= 1:
        return f"{days} day{'s' if days != 1 else ''} ago"
    hours = int(seconds // 3600)
    return f"{hours} hour{'s' if hours != 1 else ''} ago"


def load_catalogue(
    cache_file: Path | None = None,
    http: httpx.Client | None = None,
    now: float | None = None,
) -> Catalogue:
    """The catalogue from a cache under a day old, else freshly downloaded.

    If the download fails, an older cached copy is used with a warning on stderr.
    """
    path = cache_file or default_cache_file()
    now = time.time() if now is None else now
    cached = _read_cache(path)
    if cached and now - cached[1] < MAX_AGE_SECONDS:
        return cached[0]
    try:
        data = _download(http)
        catalogue = parse_catalogue(data)
    except ApiUnavailable as exc:
        if cached is None:
            raise
        print(
            f"Couldn't reach endoflife.date ({exc}); "
            f"using a cached copy from {_age(now - cached[1])}.",
            file=sys.stderr,
        )
        return cached[0]
    _write_cache(path, data)
    return catalogue
