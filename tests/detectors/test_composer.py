import json
from pathlib import Path

from eolchecker.detectors import DETECTORS, Context
from eolchecker.detectors.composer import ComposerDetector
from eolchecker.models import Dependency, Finding, Unrecognised


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
    result = run(root, "web/composer.json")
    assert result.dependencies == [
        Dependency("Composer", "laravel/framework", "10.48.2", "10.48.2", Path("web/composer.json"))]
    assert result.findings == []


def test_symfony_packages_listed(write_files):
    req = {"symfony/framework-bundle": "7.1.*", "symfony/http-kernel": "^6.4"}
    root = write_files({"composer.json": json.dumps({"require": req})})
    src = Path("composer.json")
    assert run(root).dependencies == [
        Dependency("Composer", "symfony/framework-bundle", "7.1", "7.1.*", src),
        Dependency("Composer", "symfony/http-kernel", "6.4", "^6.4", src)]


def test_unreadable_version_gap(write_files):
    root = write_files({"composer.json": json.dumps({"require": {"laravel/framework": "dev-master"}})})
    result = run(root)
    assert result.dependencies == [Dependency(
        "Composer", "laravel/framework", None, "dev-master", Path("composer.json"),
        missing="'dev-master' isn't a version")]
    assert result.unrecognised == []


def test_platform_packages_skipped(write_files):
    data = {"require": {"php": "^8.1", "ext-json": "*", "composer-plugin-api": "^2.0", "monolog/monolog": "^3.0"},
            "require-dev": {"phpunit/phpunit": "^10.0"}}
    root = write_files({"composer.json": json.dumps(data)})
    result = run(root)
    assert [d.name for d in result.dependencies] == ["monolog/monolog", "phpunit/phpunit"]
    assert [f.component for f in result.findings] == ["PHP"]


def test_broken_json_unrecognised(write_files):
    root = write_files({"composer.json": "{"})
    assert run(root).unrecognised == [Unrecognised(Path("composer.json"), "couldn't parse composer.json")]


def test_registered():
    assert any(isinstance(d, ComposerDetector) for d in DETECTORS)
