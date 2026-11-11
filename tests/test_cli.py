from pathlib import Path

from eolchecker.api import ApiUnavailable, Release
from eolchecker.cli import main
from eolchecker.models import DetectResult, Unrecognised, finding


class FakeClient:
    def releases(self, product):
        return [Release("16", "2023-05-03", True, "2024-11-08", "16.2.12"),
                Release("21", "2025-11-19", False, "2027-05-19", "21.0.1")]


class DownClient:
    def releases(self, product):
        raise ApiUnavailable("timed out")


class StubDetector:
    def __init__(self, result):
        self.result = result
        self.seen_use_maven = None

    def applies_to(self, path):
        return path.name == "package.json"

    def detect(self, path, ctx):
        self.seen_use_maven = ctx.use_maven
        return self.result


ANGULAR = DetectResult(findings=[finding("Angular", "16.2.0", "16.2.0", Path("frontend/package.json"))])


def repo(write_files):
    return write_files({"frontend/package.json": "{}"})


def test_prints_table(write_files, capsys):
    root = repo(write_files)
    assert main([str(root)], client=FakeClient(), detectors=[StubDetector(ANGULAR)]) == 0
    out = capsys.readouterr().out
    for text in ["Angular", "16.2.0", "frontend/package.json", "END OF LIFE", "Latest", "21.0.1", root.name]:
        assert text in out


def test_missing_path_exit_2(capsys):
    assert main(["/nope"], client=FakeClient(), detectors=[]) == 2
    assert "Path not found: /nope" in capsys.readouterr().err


def test_file_instead_of_folder_exit_2(write_files, capsys):
    root = repo(write_files)
    target = root / "frontend" / "package.json"
    assert main([str(target)], client=FakeClient(), detectors=[]) == 2
    assert f"Not a folder: {target}" in capsys.readouterr().err


def test_api_down_exit_1(write_files, capsys):
    root = repo(write_files)
    assert main([str(root)], client=DownClient(), detectors=[StubDetector(ANGULAR)]) == 1
    assert "Couldn't fetch end-of-life dates from endoflife.date: timed out" in capsys.readouterr().err


def test_nothing_found_exit_0(write_files, capsys):
    root = repo(write_files)
    assert main([str(root)], client=FakeClient(), detectors=[]) == 0
    assert f"No supported frameworks found in {root}" in capsys.readouterr().out


def test_not_recognised_section(write_files, capsys):
    root = repo(write_files)
    gap = DetectResult(unrecognised=[Unrecognised(Path("tools/pom.xml"), "couldn't read the Spring Boot version")])
    assert main([str(root)], client=FakeClient(), detectors=[StubDetector(gap)]) == 0
    out = capsys.readouterr().out
    assert "Not recognised:" in out
    assert "tools/pom.xml: couldn't read the Spring Boot version" in out


def test_no_maven_flag(write_files):
    root = repo(write_files)
    det = StubDetector(ANGULAR)
    main([str(root), "--no-maven"], client=FakeClient(), detectors=[det])
    assert det.seen_use_maven is False
