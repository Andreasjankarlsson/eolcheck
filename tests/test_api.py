import httpx
import pytest

from eolchecker.api import ApiUnavailable, EolClient

from .fakes import payload, product

BODY = payload(product("php", "PHP"))


def client_for(handler):
    return EolClient(httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True))


def test_products_full_200_returns_body_and_etag():
    def handler(req):
        assert req.url.path == "/api/v1/products/full"
        return httpx.Response(200, content=BODY, headers={"ETag": '"abc"'})
    resp = client_for(handler).products_full()
    assert resp.body == BODY
    assert resp.etag == '"abc"'
    assert resp.not_modified is False


def test_products_full_sends_if_none_match():
    seen = []

    def handler(req):
        seen.append(req.headers.get("If-None-Match"))
        return httpx.Response(200, content=BODY)
    client_for(handler).products_full('"abc"')
    client_for(handler).products_full()
    assert seen == ['"abc"', None]


def test_products_full_304():
    resp = client_for(lambda req: httpx.Response(304)).products_full('"abc"')
    assert resp.not_modified is True
    assert resp.body == b""


@pytest.mark.parametrize("status", [404, 500])
def test_products_full_error_status_raises(status):
    with pytest.raises(ApiUnavailable):
        client_for(lambda req: httpx.Response(status)).products_full()


def test_products_full_connect_error_raises():
    def handler(req):
        raise httpx.ConnectError("boom")
    with pytest.raises(ApiUnavailable):
        client_for(handler).products_full()


def test_follows_redirect():
    def handler(req):
        if req.url.path.endswith("/products/full"):
            return httpx.Response(301, headers={"Location": "/api/v1/products/everything"})
        return httpx.Response(200, content=BODY)
    assert client_for(handler).products_full().body == BODY
