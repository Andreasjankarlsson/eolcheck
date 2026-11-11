"""On-disk cache of endoflife.date's /products/full, and where that cache lives."""
from __future__ import annotations

import json
import os
import sys
import tomllib
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from .api import ApiUnavailable, EolClient
from .catalog import Product, parse_products

BODY_FILE = "products-full.json"
META_FILE = "products-full.meta.json"
CONFIG_FILE = "eolchecker.toml"


def checkout_root() -> Path | None:
    """The source checkout this package runs from, or None when installed elsewhere."""
    root = Path(__file__).resolve().parents[2]
    if (root / "pyproject.toml").is_file() and (root / "src" / "eolchecker").is_dir():
        return root
    return None


def user_cache_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "eolchecker"
    base = os.environ.get("XDG_CACHE_HOME")
    return (Path(base) if base else Path.home() / ".cache") / "eolchecker"


def default_cache_dir(warn: Callable[[str], None]) -> Path:
    root = checkout_root()
    if root is None:
        return user_cache_dir()
    config = root / CONFIG_FILE
    if config.is_file():
        try:
            value = tomllib.loads(config.read_text(encoding="utf-8")).get("cache_dir")
            if value is not None:
                if not isinstance(value, str):
                    raise ValueError("cache_dir must be a string")
                path = Path(value).expanduser()
                return path if path.is_absolute() else root / path
        except (OSError, ValueError) as exc:  # TOMLDecodeError is a ValueError
            warn(f"Ignoring {config}: {exc}")
    return root / ".cache"


def _read_cache(cache_dir: Path) -> tuple[list[Product], dict] | None:
    try:
        products = parse_products((cache_dir / BODY_FILE).read_bytes())
        meta = json.loads((cache_dir / META_FILE).read_text(encoding="utf-8"))
        if not isinstance(meta, dict):
            return None
        return products, meta
    except (OSError, ValueError, ApiUnavailable):
        return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _write(cache_dir: Path, body: bytes | None, etag: str | None) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    if body is not None:
        (cache_dir / BODY_FILE).write_bytes(body)
    (cache_dir / META_FILE).write_text(
        json.dumps({"etag": etag, "fetched": _now()}), encoding="utf-8")


def _write_with_fallback(cache_dir: Path, body: bytes | None, etag: str | None,
                         warn: Callable[[str], None]) -> None:
    try:
        _write(cache_dir, body, etag)
        return
    except OSError:
        pass
    fallback = user_cache_dir()
    try:
        _write(fallback, body, etag)
    except OSError:
        warn(f"Couldn't write cache in {cache_dir} or {fallback}")
        return
    warn(f"Couldn't write cache in {cache_dir}; using {fallback}")


def load_catalog(client: EolClient, cache_dir: Path, *, refresh: bool,
                 warn: Callable[[str], None]) -> list[Product]:
    cached = _read_cache(cache_dir)
    if cached is None:
        # An earlier run may have fallen back to the user cache.
        cached = _read_cache(user_cache_dir())
        if cached is not None:
            cache_dir = user_cache_dir()
    etag = cached[1].get("etag") if cached else None
    if not isinstance(etag, str):
        etag = None
    try:
        resp = client.products_full(None if refresh or cached is None else etag)
        if resp.not_modified:
            if cached is None:
                raise ApiUnavailable("HTTP 304 without cached data")
            try:
                _write(cache_dir, None, etag)  # refresh the fetched date
            except OSError:
                pass
            return cached[0]
        products = parse_products(resp.body)
    except ApiUnavailable:
        if cached is None:
            raise
        fetched = cached[1].get("fetched")
        when = fetched[:10] if isinstance(fetched, str) and fetched else "an unknown date"
        warn(f"endoflife.date unreachable; using data from {when}")
        return cached[0]
    _write_with_fallback(cache_dir, resp.body, resp.etag, warn)
    return products
