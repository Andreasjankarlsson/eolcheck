"""Builders for endoflife.date API payloads used in tests."""
from __future__ import annotations

import json

from eolchecker.catalog import PurlIndex, parse_products


def rel(name: str, release_date: str = "2024-01-01", is_eol: bool = False,
        eol_from: str | None = None, latest: str | None = None) -> dict:
    """One release cycle as the API returns it."""
    return {
        "name": name,
        "releaseDate": release_date,
        "isEol": is_eol,
        "eolFrom": eol_from,
        "latest": {"name": latest} if latest else None,
    }


def product(slug: str, label: str, purls=(), releases=()) -> dict:
    """One product as the API returns it."""
    return {
        "name": slug,
        "label": label,
        "identifiers": [{"type": "purl", "id": p} for p in purls],
        "releases": list(releases),
    }


def payload(*products: dict) -> bytes:
    return json.dumps(
        {"schema_version": "1.2.1", "total": len(products), "result": list(products)}
    ).encode()


def index(*products: dict) -> PurlIndex:
    return PurlIndex(parse_products(payload(*products)))
