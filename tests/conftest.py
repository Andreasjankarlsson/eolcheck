from pathlib import Path

import pytest


@pytest.fixture
def write_files(tmp_path: Path):
    def write(files: dict[str, str]) -> Path:
        for rel, content in files.items():
            p = tmp_path / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        return tmp_path

    return write
