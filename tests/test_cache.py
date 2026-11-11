import json

import pytest

from eolchecker import cache
from eolchecker.api import ApiUnavailable, FullResponse
from eolchecker.cache import default_cache_dir, load_catalog

from .fakes import FakeClient, payload, product

BODY = payload(product("php", "PHP"))
OK = FullResponse(False, BODY, '"e1"')
_real_user_cache_dir = cache.user_cache_dir  # the autouse fixture below replaces it


@pytest.fixture(autouse=True)
def isolated_user_cache(tmp_path_factory, monkeypatch):
    """Never touch (or read) the real user cache."""
    user = tmp_path_factory.mktemp("user")
    monkeypatch.setattr(cache, "user_cache_dir", lambda: user)


def slugs(products):
    return [p.slug for p in products]


def seed(tmp_path, fetched="2026-11-09T10:00:00+00:00"):
    (tmp_path / "products-full.json").write_bytes(BODY)
    (tmp_path / "products-full.meta.json").write_text(
        json.dumps({"etag": '"e1"', "fetched": fetched}))


def test_first_run_downloads_and_writes_cache(tmp_path):
    client = FakeClient(OK)
    assert slugs(load_catalog(client, tmp_path, refresh=False, warn=print)) == ["php"]
    assert client.etags == [None]
    assert json.loads((tmp_path / "products-full.meta.json").read_text())["etag"] == '"e1"'
    assert (tmp_path / "products-full.json").read_bytes() == BODY


def test_second_run_sends_etag_and_uses_cache_on_304(tmp_path):
    load_catalog(FakeClient(OK), tmp_path, refresh=False, warn=print)
    client = FakeClient(FullResponse(True, b"", None))
    assert slugs(load_catalog(client, tmp_path, refresh=False, warn=print)) == ["php"]
    assert client.etags == ['"e1"']
    meta = json.loads((tmp_path / "products-full.meta.json").read_text())
    assert meta["etag"] == '"e1"'


def test_refresh_ignores_etag(tmp_path):
    seed(tmp_path)
    client = FakeClient(OK)
    load_catalog(client, tmp_path, refresh=True, warn=print)
    assert client.etags == [None]


def test_network_down_uses_cache_and_warns(tmp_path):
    seed(tmp_path)
    warnings = []
    result = load_catalog(FakeClient(ApiUnavailable("down")), tmp_path,
                          refresh=False, warn=warnings.append)
    assert slugs(result) == ["php"]
    assert warnings == ["endoflife.date unreachable; using data from 2026-11-09"]


def test_non_string_etag_is_treated_as_absent(tmp_path):
    (tmp_path / "products-full.json").write_bytes(BODY)
    (tmp_path / "products-full.meta.json").write_text(json.dumps({"etag": 5, "fetched": "2026-11-09"}))
    client = FakeClient(OK)
    assert slugs(load_catalog(client, tmp_path, refresh=False, warn=print)) == ["php"]
    assert client.etags == [None]


@pytest.mark.parametrize("fetched", [None, 12345, ["x"]])
def test_network_down_with_unknown_fetched_date(tmp_path, fetched):
    (tmp_path / "products-full.json").write_bytes(BODY)
    (tmp_path / "products-full.meta.json").write_text(json.dumps({"etag": '"e1"', "fetched": fetched}))
    warnings = []
    load_catalog(FakeClient(ApiUnavailable("down")), tmp_path, refresh=False, warn=warnings.append)
    assert warnings == ["endoflife.date unreachable; using data from an unknown date"]


def test_network_down_without_cache_raises(tmp_path):
    with pytest.raises(ApiUnavailable):
        load_catalog(FakeClient(ApiUnavailable("down")), tmp_path, refresh=False, warn=print)


def test_304_without_cache_raises(tmp_path):
    with pytest.raises(ApiUnavailable):
        load_catalog(FakeClient(FullResponse(True, b"", None)), tmp_path,
                     refresh=False, warn=print)


def test_corrupt_cache_counts_as_no_cache(tmp_path):
    (tmp_path / "products-full.json").write_text("{trunc")
    (tmp_path / "products-full.meta.json").write_text("x")
    client = FakeClient(OK)
    assert slugs(load_catalog(client, tmp_path, refresh=False, warn=print)) == ["php"]
    assert client.etags == [None]
    assert (tmp_path / "products-full.json").read_bytes() == BODY


def test_unwritable_cache_dir_falls_back_to_user_cache(tmp_path, monkeypatch):
    blocker = tmp_path / "blocker"
    blocker.write_text("")
    user = tmp_path / "user"
    monkeypatch.setattr(cache, "user_cache_dir", lambda: user)
    warnings = []
    result = load_catalog(FakeClient(OK), blocker, refresh=False, warn=warnings.append)
    assert slugs(result) == ["php"]
    assert (user / "products-full.json").exists()
    assert len(warnings) == 1 and str(user) in warnings[0]


def test_user_cache_fallback_is_read_back(tmp_path, monkeypatch):
    blocker = tmp_path / "blocker"
    blocker.write_text("")
    user = tmp_path / "user"
    monkeypatch.setattr(cache, "user_cache_dir", lambda: user)
    load_catalog(FakeClient(OK), blocker, refresh=False, warn=lambda m: None)
    warnings = []
    client = FakeClient(ApiUnavailable("down"))
    result = load_catalog(client, blocker, refresh=False, warn=warnings.append)
    assert slugs(result) == ["php"]
    assert client.etags == ['"e1"']
    assert len(warnings) == 1 and "unreachable" in warnings[0]


def test_user_cache_fallback_sends_etag_without_rewarning(tmp_path, monkeypatch):
    blocker = tmp_path / "blocker"
    blocker.write_text("")
    monkeypatch.setattr(cache, "user_cache_dir", lambda: tmp_path / "user")
    load_catalog(FakeClient(OK), blocker, refresh=False, warn=lambda m: None)
    warnings = []
    client = FakeClient(FullResponse(True, b"", None))
    assert slugs(load_catalog(client, blocker, refresh=False, warn=warnings.append)) == ["php"]
    assert client.etags == ['"e1"']
    assert warnings == []


def test_double_write_failure_warns_without_claiming_fallback(tmp_path, monkeypatch):
    blocker = tmp_path / "blocker"
    blocker.write_text("")
    blocker2 = tmp_path / "blocker2"
    blocker2.write_text("")
    monkeypatch.setattr(cache, "user_cache_dir", lambda: blocker2)
    warnings = []
    result = load_catalog(FakeClient(OK), blocker, refresh=False, warn=warnings.append)
    assert slugs(result) == ["php"]
    assert warnings == [f"Couldn't write cache in {blocker} or {blocker2}"]


def test_config_cache_dir_relative_to_checkout(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "checkout_root", lambda: tmp_path)
    (tmp_path / "eolchecker.toml").write_text('cache_dir = "data"\n')
    assert default_cache_dir(print) == tmp_path / "data"


def test_config_cache_dir_expands_home(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "checkout_root", lambda: tmp_path / "checkout")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "checkout").mkdir()
    (tmp_path / "checkout" / "eolchecker.toml").write_text('cache_dir = "~/eol-cache"\n')
    assert default_cache_dir(print) == tmp_path / "home" / "eol-cache"


def test_config_cache_dir_absolute(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "checkout_root", lambda: tmp_path)
    (tmp_path / "eolchecker.toml").write_text(f'cache_dir = "{(tmp_path / "abs").as_posix()}"\n')
    assert default_cache_dir(print) == tmp_path / "abs"


def test_default_cache_dir_is_checkout_dot_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "checkout_root", lambda: tmp_path)
    assert default_cache_dir(print) == tmp_path / ".cache"


def test_no_checkout_uses_user_cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "checkout_root", lambda: None)
    monkeypatch.setattr(cache, "user_cache_dir", lambda: tmp_path / "u")
    assert default_cache_dir(print) == tmp_path / "u"


def test_broken_config_warns_and_uses_default(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "checkout_root", lambda: tmp_path)
    (tmp_path / "eolchecker.toml").write_text("cache_dir = [")
    warnings = []
    assert default_cache_dir(warnings.append) == tmp_path / ".cache"
    assert len(warnings) == 1


def test_unknown_user_in_cache_dir_warns_and_uses_default(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "checkout_root", lambda: tmp_path)
    (tmp_path / "eolchecker.toml").write_text('cache_dir = "~nosuchuser_zz9/x"\n')
    warnings = []
    assert default_cache_dir(warnings.append) == tmp_path / ".cache"
    assert len(warnings) == 1


def test_checkout_root_finds_this_repo():
    assert (cache.checkout_root() / "pyproject.toml").exists()


def test_windows_cache_dir_uses_localappdata(tmp_path, monkeypatch):
    monkeypatch.setattr(cache.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    assert _real_user_cache_dir() == tmp_path / "Local" / "eolchecker"


def test_windows_cache_dir_without_localappdata(tmp_path, monkeypatch):
    monkeypatch.setattr(cache.sys, "platform", "win32")
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setattr(cache.Path, "home", classmethod(lambda cls: tmp_path))
    assert _real_user_cache_dir() == tmp_path / "AppData" / "Local" / "eolchecker"


def test_macos_cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(cache.sys, "platform", "darwin")
    monkeypatch.setattr(cache.Path, "home", classmethod(lambda cls: tmp_path))
    assert _real_user_cache_dir() == tmp_path / "Library" / "Caches" / "eolchecker"


def test_linux_cache_dir_honours_xdg(tmp_path, monkeypatch):
    monkeypatch.setattr(cache.sys, "platform", "linux")
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    assert _real_user_cache_dir() == tmp_path / "xdg" / "eolchecker"
    monkeypatch.delenv("XDG_CACHE_HOME")
    monkeypatch.setattr(cache.Path, "home", classmethod(lambda cls: tmp_path))
    assert _real_user_cache_dir() == tmp_path / ".cache" / "eolchecker"
