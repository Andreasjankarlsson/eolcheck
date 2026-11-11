import pytest

from eolchecker import catalog
from eolchecker.api import ApiUnavailable
from eolchecker.catalog import Match, PurlIndex, dep_key, parse_products, purl_key

from .fakes import index, payload, product


@pytest.mark.parametrize("purl,key", [
    ("pkg:npm/%40angular/core", "npm:@angular/core"),
    ("pkg:npm/%40angular/core@16.0.0?x=y#sub", "npm:@angular/core"),
    ("pkg:maven/org.springframework.boot/spring-boot-starter-web", "maven:org.springframework.boot/spring-boot-starter-web"),
    ("pkg:nuget/Newtonsoft.Json", "nuget:newtonsoft.json"),
    ("pkg:composer/laravel/framework", "composer:laravel/framework"),
    ("pkg:docker/library/nginx", None),
    ("pkg:github/foo/bar", None),
    ("not a purl", None),
])
def test_purl_key(purl, key):
    assert purl_key(purl) == key


def test_dep_key_lowercases():
    assert dep_key("nuget", "Newtonsoft.Json") == "nuget:newtonsoft.json"


def test_parse_products_and_resolve():
    body = payload(product("spring-boot", "Spring Boot",
                           ["pkg:maven/org.springframework.boot/spring-boot-starter-web"],
                           [{"name": "3.4", "releaseDate": "2024-11-21", "isEol": False, "eolFrom": "2025-12-31",
                             "latest": {"name": "3.4.1"}}]))
    idx = PurlIndex(parse_products(body))
    assert idx.resolve("maven:org.springframework.boot/spring-boot-starter-web") == [Match("Spring Boot", "spring-boot")]
    assert idx.releases("spring-boot")[0].name == "3.4"
    assert idx.resolve("maven:org.projectlombok/lombok") == []
    assert idx.releases("nope") is None


def test_overrides_win_and_use_component_names():
    idx = PurlIndex(parse_products(payload(product("angular", "Angular (label)", ["pkg:npm/%40angular/core"]))))
    assert idx.resolve("npm:@angular/core") == [Match("Angular", "angular")]
    assert PurlIndex().resolve("npm:react") == [Match("React", "react")]  # overrides work without a catalogue


def test_purl_shared_by_two_products_maps_to_both():
    idx = index(product("a", "A", ["pkg:npm/shared"]), product("b", "B", ["pkg:npm/shared"]))
    assert idx.resolve("npm:shared") == [Match("A", "a"), Match("B", "b")]  # sorted by slug


def test_excluded_purls_are_ignored(monkeypatch):
    monkeypatch.setattr(catalog, "EXCLUDED_PURLS", frozenset({"npm:client-lib"}))
    assert index(product("x", "X", ["pkg:npm/client-lib"])).resolve("npm:client-lib") == []


@pytest.mark.parametrize("body", [b"not json", b'{"result": 5}', b'{"result": [{"name": "x"}]}'])
def test_bad_payload_raises(body):
    with pytest.raises(ApiUnavailable):
        parse_products(body)
