import csv
import io
import sys
from pathlib import Path

from eolchecker.api import ApiUnavailable, FullResponse
from eolchecker.cli import _make_stderr_safe, main
from eolchecker.models import Dependency, DetectResult, Unrecognised, finding

from .fakes import FakeClient, payload, product, rel

CATALOGUE = payload(
    product("angular", "Angular", ["pkg:npm/x"], [
        rel("16", "2023-05-03", True, "2024-11-08", "16.2.12"),
        rel("21", "2025-11-19", False, "2027-05-19", "21.0.1"),
    ]),
)


def ok(body: bytes = CATALOGUE, etag: str | None = '"v1"') -> FakeClient:
    return FakeClient(FullResponse(False, body, etag))


class StubDetector:
    def __init__(self, result):
        self.result = result
        self.seen_use_maven = None
        self.seen_index = None
        self.resolved = None

    def applies_to(self, path):
        return path.name == "package.json"

    def detect(self, path, ctx):
        self.seen_use_maven = ctx.use_maven
        self.seen_index = ctx.index
        self.resolved = ctx.index.resolve("npm:x")
        return self.result


ANGULAR = DetectResult(findings=[finding("Angular", "16.2.0", "16.2.0", Path("frontend/package.json"))])
UNTRACKED = DetectResult(dependencies=[
    Dependency("npm:left-pad", "left-pad", "1.0.0", "1.0.0", Path("frontend/package.json")),
])


def repo(write_files):
    return write_files({"frontend/package.json": "{}"})


def test_prints_table(write_files, tmp_path, capsys):
    root = repo(write_files)
    assert main([str(root)], client=ok(), detectors=[StubDetector(ANGULAR)], cache_dir=tmp_path / "cache") == 0
    out = capsys.readouterr().out
    for text in ["Angular", "Dependencies", "16.2.0", "frontend/package.json", "END OF LIFE", "Latest", "21.0.1", root.name]:
        assert text in out


def test_stderr_never_raises_on_a_legacy_console(monkeypatch):
    legacy = io.TextIOWrapper(io.BytesIO(), encoding="ascii")
    monkeypatch.setattr(sys, "stderr", legacy)
    _make_stderr_safe()
    print("Asking Maven about pom.xml…", file=sys.stderr, flush=True)
    assert legacy.buffer.getvalue() == b"Asking Maven about pom.xml?\n"


def test_missing_path_exit_2(tmp_path, capsys):
    assert main(["/nope"], client=ok(), detectors=[], cache_dir=tmp_path / "cache") == 2
    assert "Path not found: /nope" in capsys.readouterr().err


def test_file_instead_of_folder_exit_2(write_files, tmp_path, capsys):
    root = repo(write_files)
    target = root / "frontend" / "package.json"
    assert main([str(target)], client=ok(), detectors=[], cache_dir=tmp_path / "cache") == 2
    assert f"Not a folder: {target}" in capsys.readouterr().err


def test_api_down_without_cache_exit_1(write_files, tmp_path, capsys):
    root = repo(write_files)
    client = FakeClient(ApiUnavailable("timed out"))
    assert main([str(root)], client=client, detectors=[StubDetector(ANGULAR)], cache_dir=tmp_path / "cache") == 1
    assert "Couldn't fetch end-of-life dates from endoflife.date: timed out" in capsys.readouterr().err


def test_api_down_with_cache_warns_and_prints(write_files, tmp_path, capsys):
    root = repo(write_files)
    cache = tmp_path / "cache"
    assert main([str(root)], client=ok(), detectors=[StubDetector(ANGULAR)], cache_dir=cache) == 0
    capsys.readouterr()
    client = FakeClient(ApiUnavailable("timed out"))
    assert main([str(root)], client=client, detectors=[StubDetector(ANGULAR)], cache_dir=cache) == 0
    captured = capsys.readouterr()
    assert "endoflife.date unreachable; using data from" in captured.err
    assert "END OF LIFE" in captured.out


def test_nothing_found_exit_0(write_files, tmp_path, capsys):
    root = repo(write_files)
    assert main([str(root)], client=ok(), detectors=[], cache_dir=tmp_path / "cache") == 0
    assert f"No tracked dependencies found in {root}" in capsys.readouterr().out


def test_not_recognised_section(write_files, tmp_path, capsys):
    root = repo(write_files)
    gap = DetectResult(unrecognised=[Unrecognised(Path("tools/pom.xml"), "couldn't read the Spring Boot version")])
    assert main([str(root)], client=ok(), detectors=[StubDetector(gap)], cache_dir=tmp_path / "cache") == 0
    out = capsys.readouterr().out
    assert "Not recognised:" in out
    assert "tools/pom.xml: couldn't read the Spring Boot version" in out


def test_no_maven_flag(write_files, tmp_path):
    root = repo(write_files)
    det = StubDetector(ANGULAR)
    main([str(root), "--no-maven"], client=ok(), detectors=[det], cache_dir=tmp_path / "cache")
    assert det.seen_use_maven is False


def test_show_untracked(write_files, tmp_path, capsys):
    root = repo(write_files)
    cache = tmp_path / "cache"
    assert main([str(root)], client=ok(), detectors=[StubDetector(UNTRACKED)], cache_dir=cache) == 0
    assert "Not on endoflife.date:" not in capsys.readouterr().out
    assert main([str(root), "--show-untracked"], client=ok(), detectors=[StubDetector(UNTRACKED)], cache_dir=cache) == 0
    out = capsys.readouterr().out
    assert "Not on endoflife.date:" in out
    assert "frontend/package.json: left-pad" in out


def test_csv_written(write_files, tmp_path, capsys):
    root = repo(write_files)
    out_file = tmp_path / "out.csv"
    assert main([str(root), "--csv", str(out_file)], client=ok(), detectors=[StubDetector(ANGULAR)],
                cache_dir=tmp_path / "cache") == 0
    assert "END OF LIFE" in capsys.readouterr().out
    with out_file.open(encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f))
    assert rows[0] == ["Component", "Dependencies", "Version", "Found in", "End of support", "Latest", "Status"]
    assert rows[1][0] == "Angular"


def test_csv_to_missing_folder_exit_1(write_files, tmp_path, capsys):
    root = repo(write_files)
    target = tmp_path / "nope" / "out.csv"
    assert main([str(root), "--csv", str(target)], client=ok(), detectors=[StubDetector(ANGULAR)],
                cache_dir=tmp_path / "cache") == 1
    captured = capsys.readouterr()
    assert "END OF LIFE" in captured.out
    assert f"Couldn't write {target}" in captured.err


def test_refresh_ignores_etag(write_files, tmp_path):
    root = repo(write_files)
    cache = tmp_path / "cache"
    first = ok()
    main([str(root)], client=first, detectors=[StubDetector(ANGULAR)], cache_dir=cache)
    second = ok()
    main([str(root)], client=second, detectors=[StubDetector(ANGULAR)], cache_dir=cache)
    assert second.etags == ['"v1"']
    third = ok()
    main([str(root), "--refresh"], client=third, detectors=[StubDetector(ANGULAR)], cache_dir=cache)
    assert third.etags == [None]


def test_detectors_get_the_index(write_files, tmp_path):
    root = repo(write_files)
    det = StubDetector(ANGULAR)
    main([str(root)], client=ok(), detectors=[det], cache_dir=tmp_path / "cache")
    assert det.resolved
