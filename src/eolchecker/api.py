"""Client for the endoflife.date v1 API."""
from __future__ import annotations

from dataclasses import dataclass

import httpx

BASE_URL = "https://endoflife.date/api/v1"


@dataclass(frozen=True)
class Release:
    name: str
    release_date: str
    is_eol: bool
    eol_from: str | None
    latest: str | None


@dataclass(frozen=True)
class FullResponse:
    not_modified: bool
    body: bytes
    etag: str | None


class ApiUnavailable(Exception):
    """endoflife.date could not be reached or returned something unusable."""


class EolClient:
    def __init__(self, http: httpx.Client | None = None):
        self._http = http or httpx.Client(
            follow_redirects=True, timeout=15, headers={"User-Agent": "eolchecker/0.1"}
        )

    def products_full(self, etag: str | None = None) -> FullResponse:
        """Every product with its releases; not_modified when `etag` is still current."""
        headers = {"If-None-Match": etag} if etag else {}
        try:
            resp = self._http.get(f"{BASE_URL}/products/full", headers=headers)
        except httpx.HTTPError as exc:
            raise ApiUnavailable(str(exc) or type(exc).__name__) from exc
        if resp.status_code == 304:
            return FullResponse(True, b"", etag)
        if resp.status_code != 200:
            raise ApiUnavailable(f"HTTP {resp.status_code} for products/full")
        return FullResponse(False, resp.content, resp.headers.get("ETag"))
