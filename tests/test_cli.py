from pathlib import Path

from eolchecker.catalogue import ApiUnavailable
from eolchecker.cli import main
from eolchecker.models import DetectResult, Dependency, Unrecognised

from .catalogue_fixture import catalogue as fixture_catalogue


def down_catalogue():
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


ANGULAR = DetectResult(dependencies=[
    Dependency("npm", "@angular/core", "16.2.0", "16.2.0", Path("frontend/package.json"))])


def repo(write_files):
    return write_files({"frontend/package.json": "{}"})


def test_prints_table(write_files, capsys):
    root = repo(write_files)
    assert main([str(root)], catalogue=fixture_catalogue, detectors=[StubDetector(ANGULAR)]) == 0
    out = capsys.readouterr().out
    for text in ["Angular", "16.2.0", "frontend/package.json", "END OF LIFE", "Latest", "20.3.0", root.name]:
        assert text in out


def test_missing_path_exit_2(capsys):
    assert main(["/nope"], catalogue=fixture_catalogue, detectors=[]) == 2
    assert "Path not found: /nope" in capsys.readouterr().err


def test_file_instead_of_folder_exit_2(write_files, capsys):
    root = repo(write_files)
    target = root / "frontend" / "package.json"
    assert main([str(target)], catalogue=fixture_catalogue, detectors=[]) == 2
    assert f"Not a folder: {target}" in capsys.readouterr().err


def test_api_down_exit_1(write_files, capsys):
    root = repo(write_files)
    assert main([str(root)], catalogue=down_catalogue, detectors=[StubDetector(ANGULAR)]) == 1
    assert "Couldn't fetch end-of-life dates from endoflife.date: timed out" in capsys.readouterr().err


def test_not_recognised_section(write_files, capsys):
    root = repo(write_files)
    gap = DetectResult(unrecognised=[Unrecognised(Path("tools/pom.xml"), "couldn't read the Spring Boot version")])
    assert main([str(root)], catalogue=fixture_catalogue, detectors=[StubDetector(gap)]) == 0
    out = capsys.readouterr().out
    assert "Not recognised:" in out
    assert "tools/pom.xml: couldn't read the Spring Boot version" in out


def test_no_maven_flag(write_files):
    root = repo(write_files)
    det = StubDetector(ANGULAR)
    main([str(root), "--no-maven"], catalogue=fixture_catalogue, detectors=[det])
    assert det.seen_use_maven is False


def test_nothing_found_message_skips_catalogue(write_files, capsys):
    root = repo(write_files)

    def boom():
        raise AssertionError("catalogue must not be loaded")

    assert main([str(root)], catalogue=boom, detectors=[]) == 0
    assert f"No dependencies found in {root}" in capsys.readouterr().out


def test_only_untracked(write_files, capsys):
    root = repo(write_files)
    leftpad = DetectResult(dependencies=[
        Dependency("npm", "left-pad", "1.3.0", "1.3.0", Path("frontend/package.json"))])
    assert main([str(root)], catalogue=fixture_catalogue, detectors=[StubDetector(leftpad)]) == 0
    assert "No dependencies tracked by endoflife.date found." in capsys.readouterr().out


def test_sbom_csv(write_files, tmp_path, capsys):
    root = repo(write_files)
    out_file = tmp_path / "sbom.csv"
    code = main([str(root), "--sbom", str(out_file)], catalogue=fixture_catalogue,
                detectors=[StubDetector(ANGULAR)])
    assert code == 0
    lines = out_file.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "Ecosystem,Name,Version,Found in,Product,End of support,Status"
    assert any("@angular/core" in line and "16.2.0" in line for line in lines[1:])
    out = capsys.readouterr().out
    assert "END OF LIFE" in out
    assert "SBOM written to" in out


def test_sbom_markdown(write_files, tmp_path, capsys):
    root = repo(write_files)
    out_file = tmp_path / "sbom.md"
    code = main([str(root), "--sbom", str(out_file)], catalogue=fixture_catalogue,
                detectors=[StubDetector(ANGULAR)])
    assert code == 0
    lines = out_file.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("| Ecosystem | Name |")
    assert any("@angular/core" in line for line in lines[2:])
    assert "END OF LIFE" in capsys.readouterr().out


def test_sbom_header_only_when_nothing_found(write_files, tmp_path):
    root = repo(write_files)
    out_file = tmp_path / "sbom.csv"
    assert main([str(root), "--sbom", str(out_file)], catalogue=fixture_catalogue, detectors=[]) == 0
    assert out_file.read_text(encoding="utf-8").splitlines() == [
        "Ecosystem,Name,Version,Found in,Product,End of support,Status"]


def test_sbom_bad_suffix_exit_2(capsys):
    def boom(*a, **k):
        raise AssertionError("must not scan")

    assert main(["/nope", "--sbom", "out.txt"], catalogue=boom, detectors=[]) == 2
    assert "--sbom file must end in .csv or .md" in capsys.readouterr().err


def test_sbom_unwritable_exit_1(write_files, tmp_path, capsys):
    root = repo(write_files)
    target = tmp_path / "missing" / "sbom.csv"
    code = main([str(root), "--sbom", str(target)], catalogue=fixture_catalogue,
                detectors=[StubDetector(ANGULAR)])
    assert code == 1
    captured = capsys.readouterr()
    assert "Couldn't write" in captured.err
    assert "END OF LIFE" in captured.out


def test_version_not_found_style():
    from io import StringIO

    from rich.console import Console

    from eolchecker.report import render
    from eolchecker.rows import Row

    buf = StringIO()
    console = Console(file=buf, force_terminal=True, color_system="standard", width=200)
    render("repo", [Row("Angular", "1.0", "a", "", "", "version not found")], [], console)
    out = buf.getvalue()
    assert "version not found" in out
    assert "\x1b[2mversion not found" in out
