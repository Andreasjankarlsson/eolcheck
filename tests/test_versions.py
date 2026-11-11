import pytest

from eolchecker.versions import cycle_candidates, is_range, lowest, normalise


@pytest.mark.parametrize("raw,expected", [
    ("3.1.5", "3.1.5"), ("v6.4.1", "6.4.1"), ("6.4.1.Final", "6.4.1"),
    ("3.2.0-RC1", "3.2.0"), ("18", "18"), ("v18.17.0", "18.17.0"),
    ("latest", None), ("", None),
])
def test_normalise(raw, expected):
    assert normalise(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("^16.2.0", True), ("~3.1", True), (">=7.4", True), ("16.x", True),
    ("^7.4|^8.0", True), ("^7.4 || ^8.0", True), ("16.2.0", False), ("8.2", False),
])
def test_is_range(raw, expected):
    assert is_range(raw) is expected


@pytest.mark.parametrize("raw,expected", [
    ("^16.2.0", "16.2.0"), ("~3.1", "3.1"), (">=7.4", "7.4"), ("16.x", "16"),
    ("^8.0|^7.4", "7.4"), ("^8.0 || ^7.4", "7.4"), (">=18 <21", "18"),
    ("16.2.0", "16.2.0"), ("*", None), ("latest", None),
    ("workspace:*", None), ("git+https://github.com/x/y.git", None),
])
def test_lowest(raw, expected):
    assert lowest(raw) == expected


def test_cycle_candidates():
    assert cycle_candidates("4.7.2") == ["4.7.2", "4.7", "4"]
    assert cycle_candidates("17") == ["17"]
    assert cycle_candidates("8.0") == ["8.0", "8"]
