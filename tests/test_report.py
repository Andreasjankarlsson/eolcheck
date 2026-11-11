import csv
import io
from pathlib import Path, PureWindowsPath

import pytest
from rich.console import Console

from eolchecker.models import Unrecognised
from eolchecker.report import render, write_csv
from eolchecker.rows import Row

ROW = Row("Spring Boot", ("spring-boot-starter-test", "spring-boot-starter-web"), "3.2.0 (also 3.4.1)",
          "backend/pom.xml", "2024-11-23", "4.1.2", "END OF LIFE")
DASH_ROW = Row("Java", (), "17", "pom.xml", "—", "—", "unknown version")


def _out(rows, unrecognised=(), untracked=None, width=200) -> str:
    buf = io.StringIO()
    render("repo", rows, list(unrecognised), Console(file=buf, width=width), untracked)
    return buf.getvalue()


NARROW_ROWS = [
    Row("Spring Boot", ("spring-boot-starter-parent (parent)", "spring-boot-starter-web",
                        "spring-boot-starter-test"),
        "3.2.0 (also 3.4.1)", "backend/service-a/pom.xml", "2024-11-23", "4.1.2", "END OF LIFE"),
    Row("Java", ("maven.compiler.release",), "17", "backend/service-a/pom.xml", "2029-09-30", "27.0.1",
        "supported"),
    Row("Spring Framework", ("spring-core", "spring-context"), "6.1.2", "backend/service-a/pom.xml",
        "2025-08-31", "7.0.1", "END OF LIFE"),
]


@pytest.mark.parametrize("width", [80, 100])
def test_narrow_terminal_keeps_key_cells_whole(width):
    lines = _out(NARROW_ROWS, width=width).splitlines()
    assert all(len(line) <= width for line in lines)
    # Component, Status and the file path are never broken; Version only wraps at its space.
    for text in ["backend/service-a/pom.xml", "END OF LIFE", "Spring Boot", "Spring Framework", "supported",
                 "3.2.0", "(also", "3.4.1)"]:
        assert any(text in line for line in lines), text
    assert sum("backend/service-a/pom.xml" in line for line in lines) == 3


def test_100_columns_keeps_dates_and_dependency_names_readable():
    out = _out(NARROW_ROWS, width=100)
    for text in ["2024-11-23", "2029-09-30", "27.0.1", "spring-core,", "spring-context"]:
        assert text in out
    assert len(out.splitlines()) <= 15


def test_cells_are_escaped():
    row = Row("Spring [bold]Boot", ("a[/b]",), "[1.0]", "a[/b]/package.json", "[/x]", "[/y]", "supported")
    out = _out([row])
    for text in ["Spring [bold]Boot", "a[/b]/package.json", "[1.0]", "[/x]", "[/y]"]:
        assert text in out


def test_table_has_dependencies_column():
    out = _out([ROW])
    header = next(line for line in out.splitlines() if "Component" in line)
    assert header.split() == ["Component", "Dependencies", "Version", "Found", "in", "End", "of", "support", "Latest", "Status"]
    assert "spring-boot-starter-test, spring-boot-starter-web" in out


def test_long_dependencies_cell_never_cuts_off_other_columns():
    deps = tuple(f"spring-boot-starter-{n}" for n in ["web", "data-jpa", "security", "validation", "actuator", "test"])
    row = Row("Spring Boot", deps, "3.2.0 (also 3.4.1)", "backend/services/payments/pom.xml",
              "2024-11-23", "4.1.2", "END OF LIFE")
    out = _out([row])
    for text in ["END OF LIFE", "Spring Boot", "3.2.0 (also 3.4.1)", *deps]:
        assert text in out


def test_untracked_section():
    out = _out([ROW], [Unrecognised(Path("a/pom.xml"), "bad")],
               {Path("backend/pom.xml"): ["lombok", "slf4j-api"]})
    assert "Not on endoflife.date:" in out
    assert "  backend/pom.xml: lombok, slf4j-api" in out
    assert out.index("Not recognised:") < out.index("Not on endoflife.date:")


def test_untracked_hidden_when_none():
    assert "Not on endoflife.date" not in _out([ROW])
    assert "Not on endoflife.date" not in _out([ROW], untracked={})


def test_csv(tmp_path):
    write_csv(tmp_path / "r.csv", [ROW], [Unrecognised(Path("a/pom.xml"), "couldn't resolve ${x}")], {Path("a/pom.xml"): ["lombok"]})
    assert list(csv.reader((tmp_path / "r.csv").open(encoding="utf-8", newline=""))) == [
        ["Component", "Dependencies", "Version", "Found in", "End of support", "Latest", "Status"],
        ["Spring Boot", "spring-boot-starter-test; spring-boot-starter-web", "3.2.0 (also 3.4.1)", "backend/pom.xml", "2024-11-23", "4.1.2", "END OF LIFE"],
        ["", "couldn't resolve ${x}", "", "a/pom.xml", "", "", "not recognised"],
        ["", "lombok", "", "a/pom.xml", "", "", "not tracked"],
    ]


def test_windows_paths_print_and_write_with_forward_slashes(tmp_path):
    win = PureWindowsPath("backend") / "pom.xml"
    out = _out([], unrecognised=[Unrecognised(win, "couldn't parse pom.xml")], untracked={win: ["lombok"]})
    assert "  backend/pom.xml: couldn't parse pom.xml" in out
    assert "  backend/pom.xml: lombok" in out
    assert "\\" not in out
    write_csv(tmp_path / "r.csv", [], [Unrecognised(win, "x")], {win: ["lombok"]})
    rows = list(csv.reader((tmp_path / "r.csv").open(encoding="utf-8", newline="")))
    assert [r[3] for r in rows[1:]] == ["backend/pom.xml", "backend/pom.xml"]


def test_csv_dash_cells_are_empty(tmp_path):
    write_csv(tmp_path / "r.csv", [DASH_ROW], [])
    rows = list(csv.reader((tmp_path / "r.csv").open(encoding="utf-8", newline="")))
    assert rows[1] == ["Java", "", "17", "pom.xml", "", "", "unknown version"]


def test_csv_without_untracked_has_no_not_tracked_rows(tmp_path):
    write_csv(tmp_path / "r.csv", [ROW], [])
    text = (tmp_path / "r.csv").read_text(encoding="utf-8")
    assert "not tracked" not in text
    assert len(text.strip().splitlines()) == 2
