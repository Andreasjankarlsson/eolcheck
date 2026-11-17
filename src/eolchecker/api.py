"""Client for the endoflife.date v1 API."""
from __future__ import annotations

import httpx

from .catalogue import ApiUnavailable, Release

BASE_URL = "https://endoflife.date/api/v1"


class EolClient:
    def __init__(self, http: httpx.Client | None = None):
        self._http = http or httpx.Client(
            follow_redirects=True, timeout=15, headers={"User-Agent": "eolchecker/0.1"}
        )

    def releases(self, product: str) -> list[Release] | None:
        """All release cycles for a product, or None if endoflife.date doesn't know it."""
        try:
            resp = self._http.get(f"{BASE_URL}/products/{product}")
        except httpx.HTTPError as exc:
            raise ApiUnavailable(str(exc) or type(exc).__name__) from exc
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise ApiUnavailable(f"HTTP {resp.status_code} for {product}")
        try:
            raw = resp.json()["result"]["releases"]
            return [
                Release(
                    name=r["name"],
                    release_date=r.get("releaseDate") or "",
                    is_eol=bool(r.get("isEol")),
                    eol_from=r.get("eolFrom"),
                    latest=(r.get("latest") or {}).get("name"),
                )
                for r in raw
            ]
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise ApiUnavailable(f"unexpected response for {product}") from exc
