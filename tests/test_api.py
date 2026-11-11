import httpx
import pytest

from eolchecker.api import ApiUnavailable, EolClient, Release

PAYLOAD = {"result": {"releases": [{
    "name": "3.1", "releaseDate": "2023-05-18", "isEol": True,
    "eolFrom": "2024-06-30", "latest": {"name": "3.1.12"},
}]}}


def client_for(handler):
    return EolClient(httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True))


def test_releases_parses_v1_payload():
    def handler(req):
        assert req.url.path == "/api/v1/products/spring-boot"
        return httpx.Response(200, json=PAYLOAD)
    assert client_for(handler).releases("spring-boot") == [
        Release("3.1", "2023-05-18", True, "2024-06-30", "3.1.12")
    ]


def test_404_returns_none():
    assert client_for(lambda req: httpx.Response(404, text="<html>")).releases("nope") is None


@pytest.mark.parametrize("status", [429, 500])
def test_error_status_raises(status):
    with pytest.raises(ApiUnavailable):
        client_for(lambda req: httpx.Response(status)).releases("spring-boot")


def test_connect_error_raises():
    def handler(req):
        raise httpx.ConnectError("boom")
    with pytest.raises(ApiUnavailable):
        client_for(handler).releases("spring-boot")


def test_bad_json_raises():
    with pytest.raises(ApiUnavailable):
        client_for(lambda req: httpx.Response(200, text="not json")).releases("spring-boot")


def test_follows_redirect():
    def handler(req):
        if req.url.path.endswith("/old-name"):
            return httpx.Response(301, headers={"Location": "/api/v1/products/new-name"})
        return httpx.Response(200, json=PAYLOAD)
    assert client_for(handler).releases("old-name")[0].name == "3.1"
