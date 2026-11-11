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
    assert run(root).findings == [Finding("PHP", "php", "7.4", ">=7.4", Path("composer.json"),
                                                origin="require.php")]


def test_platform_php_wins(write_files):
    data = {"require": {"php": "^8.1"}, "config": {"platform": {"php": "8.2.10"}}}
    root = write_files({"composer.json": json.dumps(data)})
    [f] = run(root).findings
    assert (f.version, f.display) == ("8.2.10", "8.2.10")


def test_laravel_from_lock(write_files):
    lock = {"packages": [{"name": "laravel/framework", "version": "v10.48.2"}], "packages-dev": []}
    root = write_files({"web/composer.json": json.dumps({"require": {"laravel/framework": "^10.0"}}),
                        "web/composer.lock": json.dumps(lock)})
    assert run(root, "web/composer.json").dependencies == [
        Dependency("composer:laravel/framework", "laravel/framework", "10.48.2", "10.48.2",
                   Path("web/composer.json"))]


def test_symfony_framework_bundle(write_files):
    root = write_files({"composer.json": json.dumps({"require": {"symfony/framework-bundle": "7.1.*"}})})
    assert run(root).dependencies == [
        Dependency("composer:symfony/framework-bundle", "symfony/framework-bundle", "7.1", "7.1.*",
                   Path("composer.json"))]


def test_symfony_both_packages_one_dependency_each(write_files):
    req = {"symfony/framework-bundle": "^7.1", "symfony/http-kernel": "^7.1"}
    root = write_files({"composer.json": json.dumps({"require": req})})
    assert [d.name for d in run(root).dependencies] == ["symfony/framework-bundle", "symfony/http-kernel"]


def test_unreadable_version_gap(write_files):
    root = write_files({"composer.json": json.dumps({"require": {"laravel/framework": "dev-master"}})})
    assert run(root).unrecognised == [Unrecognised(Path("composer.json"), "couldn't read the Laravel version")]


def test_require_and_require_dev(write_files):
    data = {"require": {"monolog/monolog": "^3.0"}, "require-dev": {"phpunit/phpunit": "^10.5"}}
    root = write_files({"composer.json": json.dumps(data)})
    result = run(root)
    assert result.dependencies == [
        Dependency("composer:monolog/monolog", "monolog/monolog", "3.0", "^3.0", Path("composer.json")),
        Dependency("composer:phpunit/phpunit", "phpunit/phpunit", "10.5", "^10.5", Path("composer.json"))]
    assert (result.findings, result.unrecognised) == ([], [])


def test_platform_packages_skipped(write_files):
    req = {"php": ">=8.1", "ext-json": "*", "lib-curl": "*", "composer-plugin-api": "^2.0",
           "monolog/monolog": "^3"}
    root = write_files({"composer.json": json.dumps({"require": req})})
    assert [d.name for d in run(root).dependencies] == ["monolog/monolog"]


def test_php_origin(write_files):
    root = write_files({"composer.json": json.dumps({"require": {"php": "^8.1"}})})
    assert run(root).findings[0].origin == "require.php"
    data = {"require": {"php": "^8.1"}, "config": {"platform": {"php": "8.2.10"}}}
    root = write_files({"composer.json": json.dumps(data)})
    assert run(root).findings[0].origin == "config.platform.php"


def test_broken_json_unrecognised(write_files):
    root = write_files({"composer.json": "{"})
    assert run(root).unrecognised == [Unrecognised(Path("composer.json"), "couldn't parse composer.json")]


def test_registered():
    assert any(isinstance(d, ComposerDetector) for d in DETECTORS)
