import os
from pathlib import Path

from eolchecker.detectors import Context
from eolchecker.models import DetectResult, Unrecognised, finding
from eolchecker.scan import iter_files, scan


class FakeDetector:
    def applies_to(self, path):
        return path.suffix == ".json"

    def detect(self, path, ctx):
        if path.name == "bad.json":
            raise ValueError("boom")
        return DetectResult(findings=[finding("React", "18", "18", path.relative_to(ctx.root))])


def test_skips_ignored_dirs(write_files):
    root = write_files({"node_modules/x/package.json": "{}", "vendor/a/composer.json": "{}",
                        "app/package.json": "{}"})
    assert [p.relative_to(root) for p in iter_files(root)] == [Path("app/package.json")]


def test_does_not_follow_symlink_loop(write_files):
    root = write_files({"a/package.json": "{}"})
    os.symlink(root, root / "loop")
    assert [p.relative_to(root) for p in iter_files(root)] == [Path("a/package.json")]


def test_detector_exception_becomes_unrecognised(write_files):
    root = write_files({"bad.json": "{"})
    result = scan(root, Context(root), [FakeDetector()])
    assert result.unrecognised == [Unrecognised(Path("bad.json"), "couldn't parse bad.json")]


def test_scan_collects_findings_with_relative_paths(write_files):
    root = write_files({"web/package.json": "{}", "README.md": ""})
    result = scan(root, Context(root), [FakeDetector()])
    assert [f.source for f in result.findings] == [Path("web/package.json")]
