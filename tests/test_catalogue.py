import json
import os
import sys

import httpx
import pytest

from .catalogue_fixture import FULL, catalogue
from eolchecker.catalogue import (
    ApiUnavailable, Release, default_cache_file, load_catalogue, parse_catalogue,
)

HOUR = 3600
DAY = 24 * HOUR


def http_returning(payload, calls=None):
    def handler(req):
        assert req.url.path == "/api/v1/products/full"
        if calls is not None:
            calls.append(req)
        return httpx.Response(200, json=payload)
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def failing_http(exc=None):
    def handler(req):
        raise exc or httpx.ConnectError("boom")
    return httpx.Client(transport=httpx.MockTransport(handler))


def status_http(status):
    return httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(status)))


def write_cache(path, age, now, text=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text if text is not None else json.dumps(FULL))
    os.utime(path, (now - age, now - age))


def test_parse_fixture():
    cat = catalogue()
    boot = cat.product("spring-boot")
    assert boot.label == "Spring Boot"
    assert "pkg:maven/org.springframework.boot/spring-boot-starter-web" in boot.purls
    assert boot.releases[1] == Release("3.2", "2023-11-23", True, "2024-12-31", "3.2.12")
    assert cat.product("debian").releases[0].codename == "Bookworm"
    assert cat.product("nope") is None
    assert len(cat.products()) == len(FULL["result"])


def test_bad_shape_raises():
    with pytest.raises(ApiUnavailable):
        parse_catalogue({"result": [{"name": "x"}]})


def test_downloads_and_writes_cache(tmp_path):
    cache = tmp_path / "c" / "products-full.json"
    cat = load_catalogue(cache, http_returning(FULL), now=1000.0)
    assert cat.product("php") and json.loads(cache.read_text()) == FULL


def test_fresh_cache_skips_network(tmp_path):
    cache = tmp_path / "products-full.json"
    write_cache(cache, HOUR, 10_000_000.0)
    assert load_catalogue(cache, failing_http(), now=10_000_000.0).product("php")


def test_old_cache_is_refreshed(tmp_path):
    cache = tmp_path / "products-full.json"
    write_cache(cache, 25 * HOUR, 10_000_000.0, text=json.dumps({"result": []}))
    calls = []
    cat = load_catalogue(cache, http_returning(FULL, calls), now=10_000_000.0)
    assert len(calls) == 1
    assert cat.product("php")
    assert json.loads(cache.read_text()) == FULL


def test_stale_cache_used_when_offline(tmp_path, capsys):
    cache = tmp_path / "products-full.json"
    now = 10_000_000.0
    write_cache(cache, 3 * DAY, now)
    assert load_catalogue(cache, failing_http(), now=now).product("php")
    assert "using a cached copy from 3 days ago" in capsys.readouterr().err


def test_offline_without_cache_raises(tmp_path):
    with pytest.raises(ApiUnavailable):
        load_catalogue(tmp_path / "products-full.json", failing_http(), now=1000.0)


def test_corrupt_cache_ignored(tmp_path):
    cache = tmp_path / "products-full.json"
    now = 10_000_000.0
    write_cache(cache, HOUR, now, text="{")
    with pytest.raises(ApiUnavailable):
        load_catalogue(cache, failing_http(), now=now)
    assert load_catalogue(cache, http_returning(FULL), now=now).product("php")
    assert json.loads(cache.read_text()) == FULL


def test_http_error_status_without_cache_raises(tmp_path):
    with pytest.raises(ApiUnavailable):
        load_catalogue(tmp_path / "products-full.json", status_http(500), now=1000.0)


def test_default_cache_file_xdg(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    assert default_cache_file() == tmp_path / "eolchecker" / "products-full.json"
