import json
from pathlib import Path

from eolchecker.detectors import DETECTORS, Context
from eolchecker.detectors.composer import ComposerDetector
from eolchecker.models import Finding, Unrecognised


def run(root: Path, rel: str = "composer.json"):
    return ComposerDetector().detect(root / rel, Context(root))


def test_applies_to():
    assert ComposerDetector().applies_to(Path("web/composer.json"))
    assert not ComposerDetector().applies_to(Path("web/composer.lock"))


def test_php_range(write_files):
    root = write_files({"composer.json": json.dumps({"require": {"php": ">=7.4"}})})
    assert run(root).findings == [Finding("PHP", "php", "7.4", ">=7.4", Path("composer.json"))]


def test_platform_php_wins(write_files):
    data = {"require": {"php": "^8.1"}, "config": {"platform": {"php": "8.2.10"}}}
    root = write_files({"composer.json": json.dumps(data)})
    [f] = run(root).findings
    assert (f.version, f.display) == ("8.2.10", "8.2.10")


def test_laravel_from_lock(write_files):
    lock = {"packages": [{"name": "laravel/framework", "version": "v10.48.2"}], "packages-dev": []}
    root = write_files({"web/composer.json": json.dumps({"require": {"laravel/framework": "^10.0"}}),
                        "web/composer.lock": json.dumps(lock)})
    assert run(root, "web/composer.json").findings == [
        Finding("Laravel", "laravel", "10.48.2", "10.48.2", Path("web/composer.json"))]


def test_symfony_framework_bundle(write_files):
    root = write_files({"composer.json": json.dumps({"require": {"symfony/framework-bundle": "7.1.*"}})})
    [f] = run(root).findings
    assert (f.component, f.version, f.display) == ("Symfony", "7.1", "7.1.*")


def test_symfony_http_kernel_fallback(write_files):
    root = write_files({"composer.json": json.dumps({"require": {"symfony/http-kernel": "^6.4"}})})
    assert run(root).findings == [Finding("Symfony", "symfony", "6.4", "^6.4", Path("composer.json"))]


def test_unreadable_version_gap(write_files):
    root = write_files({"composer.json": json.dumps({"require": {"laravel/framework": "dev-master"}})})
    assert run(root).unrecognised == [Unrecognised(Path("composer.json"), "couldn't read the Laravel version")]


def test_no_frameworks_silent(write_files):
    root = write_files({"composer.json": json.dumps({"require": {"monolog/monolog": "^3"}})})
    result = run(root)
    assert (result.findings, result.unrecognised) == ([], [])


def test_broken_json_unrecognised(write_files):
    root = write_files({"composer.json": "{"})
    assert run(root).unrecognised == [Unrecognised(Path("composer.json"), "couldn't parse composer.json")]


def test_registered():
    assert any(isinstance(d, ComposerDetector) for d in DETECTORS)
