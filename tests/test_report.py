import csv
import io
from pathlib import Path

from rich.console import Console

from eolchecker.models import Unrecognised
from eolchecker.report import render, write_csv
from eolchecker.rows import Row

ROW = Row("Spring Boot", ("spring-boot-starter-test", "spring-boot-starter-web"), "3.2.0 (also 3.4.1)",
          "backend/pom.xml", "2024-11-23", "4.1.2", "END OF LIFE")
DASH_ROW = Row("Java", (), "17", "pom.xml", "—", "—", "unknown version")


def _out(rows, unrecognised=(), untracked=None) -> str:
    buf = io.StringIO()
    render("repo", rows, list(unrecognised), Console(file=buf, width=200), untracked)
    return buf.getvalue()


def test_table_has_dependencies_column():
    out = _out([ROW])
    header = next(line for line in out.splitlines() if "Component" in line)
    assert header.split() == ["Component", "Dependencies", "Version", "Found", "in", "End", "of", "support", "Latest", "Status"]
    assert "spring-boot-starter-test, spring-boot-starter-web" in out


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


def test_csv_dash_cells_are_empty(tmp_path):
    write_csv(tmp_path / "r.csv", [DASH_ROW], [])
    rows = list(csv.reader((tmp_path / "r.csv").open(encoding="utf-8", newline="")))
    assert rows[1] == ["Java", "", "17", "pom.xml", "", "", "unknown version"]


def test_csv_without_untracked_has_no_not_tracked_rows(tmp_path):
    write_csv(tmp_path / "r.csv", [ROW], [])
    text = (tmp_path / "r.csv").read_text(encoding="utf-8")
    assert "not tracked" not in text
    assert len(text.strip().splitlines()) == 2
