from __future__ import annotations

import pytest

from eolchecker.rows import SbomRow
from eolchecker.sbom import to_csv, to_markdown, write_sbom

ROW = SbomRow("npm", "react", "^18.2.0", "web/package.json", "React", "", "no EOL date")


def test_csv():
    assert to_csv([ROW]) == (
        "Ecosystem,Name,Version,Found in,Product,End of support,Status\n"
        "npm,react,^18.2.0,web/package.json,React,,no EOL date\n"
    )


def test_csv_quotes_commas():
    row = SbomRow("npm", "a,b", "1", "p.json", "", "", "")
    assert '"a,b"' in to_csv([row])


def test_markdown():
    assert to_markdown([ROW]).splitlines() == [
        "| Ecosystem | Name | Version | Found in | Product | End of support | Status |",
        "|---|---|---|---|---|---|---|",
        "| npm | react | ^18.2.0 | web/package.json | React |  | no EOL date |",
    ]


def test_markdown_escapes_pipes():
    row = SbomRow("npm", "x", ">=1 || <2", "p.json", "", "", "")
    assert ">=1 \\|\\| <2" in to_markdown([row])


def test_write_sbom_by_suffix(tmp_path):
    csv_path = tmp_path / "out.csv"
    md_path = tmp_path / "out.MD"
    write_sbom(csv_path, [ROW])
    write_sbom(md_path, [ROW])
    assert csv_path.read_text(encoding="utf-8") == to_csv([ROW])
    assert md_path.read_text(encoding="utf-8") == to_markdown([ROW])


def test_write_sbom_bad_suffix(tmp_path):
    with pytest.raises(ValueError):
        write_sbom(tmp_path / "out.txt", [ROW])
