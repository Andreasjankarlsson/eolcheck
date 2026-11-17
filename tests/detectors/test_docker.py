from pathlib import Path

import pytest

from eolchecker.detectors import DETECTORS, Context
from eolchecker.detectors.docker import DockerDetector, split_image
from eolchecker.models import Dependency, Unrecognised


def run(root: Path, rel: str = "Dockerfile"):
    return DockerDetector().detect(root / rel, Context(root))


@pytest.mark.parametrize("name, ok", [
    ("Dockerfile", True), ("Dockerfile.prod", True), ("api.Dockerfile", True),
    ("web.dockerfile", True), ("docker-compose.yml", True), ("docker-compose.override.yaml", True),
    ("compose.yaml", True), ("compose.dev.yml", True), ("Dockerfile.md", True),
    ("docker-compose-prod.yml", True), ("compose-dev.yaml", True),
    ("README.md", False), ("composer.json", False), ("composer.lock", False)])
def test_applies_to(name, ok):
    assert DockerDetector().applies_to(Path("x") / name) is ok


def test_from_line(write_files):
    root = write_files({"Dockerfile": "FROM node:18-alpine3.19\n"})
    assert run(root).dependencies == [
        Dependency("Docker", "node", "18", "18-alpine3.19", Path("Dockerfile"), tag="18-alpine3.19")]


def test_multi_stage_platform_and_arg(write_files):
    root = write_files({"Dockerfile": "ARG NODE=18\nFROM --platform=$BUILDPLATFORM node:${NODE}-bullseye AS build\n"
                                      "RUN x\nFROM build\nFROM scratch\n"})
    [dep] = run(root).dependencies
    assert (dep.name, dep.version, dep.tag) == ("node", "18", "18-bullseye")


def test_registry_port_is_not_a_tag():
    assert split_image("localhost:5000/app:1.2") == ("localhost:5000/app", "1.2", None)
    assert split_image("localhost:5000/app") == ("localhost:5000/app", None, None)
    assert split_image("node@sha256:abc") == ("node", None, "sha256:abc")


@pytest.mark.parametrize("line, display, missing", [
    ("FROM node", "latest", "image tag doesn't pin a version"),
    ("FROM node:latest", "latest", "image tag doesn't pin a version"),
    ("FROM node:lts-slim", "lts-slim", "image tag doesn't pin a version"),
    ("FROM node@sha256:abc", "sha256:abc", "image pinned by digest only"),
    ("FROM node:${V}", "${V}", "image tag set by a build variable"),
])
def test_unpinned(write_files, line, display, missing):
    root = write_files({"Dockerfile": line + "\n"})
    [dep] = run(root).dependencies
    assert dep.version is None
    assert (dep.display, dep.missing) == (display, missing)
    assert dep.tag == (None if line in ("FROM node", "FROM node@sha256:abc") else display)


def test_digest_with_tag_uses_tag(write_files):
    root = write_files({"Dockerfile": "FROM node:18@sha256:abc\n"})
    [dep] = run(root).dependencies
    assert (dep.name, dep.version, dep.tag) == ("node", "18", "18")


def test_os_image_codename_tag(write_files):
    root = write_files({"Dockerfile": "FROM debian:bookworm-slim\n"})
    [dep] = run(root).dependencies
    assert (dep.version, dep.tag, dep.missing) == (None, "bookworm-slim", "image tag doesn't pin a version")


def test_line_continuation(write_files):
    root = write_files({"Dockerfile": "FROM \\\n  node:18\n"})
    [dep] = run(root).dependencies
    assert (dep.name, dep.version) == ("node", "18")


def test_lowercase_from_and_alias_case(write_files):
    root = write_files({"Dockerfile": "from node:20 as Build\nFROM build\n"})
    assert [d.name for d in run(root).dependencies] == ["node"]


def test_compose_images(write_files):
    root = write_files({"docker-compose.yml": (
        "services:\n  db:\n    image: \"postgres:16\"\n"
        "  web:\n    image: \"${REG:-ghcr.io/acme}/web:${TAG:-1.4}\"\n"
        "  app:\n    build: .\n")})
    deps = run(root, "docker-compose.yml").dependencies
    assert [(d.name, d.version) for d in deps] == [("postgres", "16"), ("ghcr.io/acme/web", "1.4")]


def test_compose_dashed_filename_is_read(write_files):
    root = write_files({"docker-compose-prod.yml": "services:\n  db:\n    image: postgres:16\n"})
    deps = run(root, "docker-compose-prod.yml").dependencies
    assert [(d.name, d.version) for d in deps] == [("postgres", "16")]


def test_compose_variable_without_default(write_files):
    root = write_files({"compose.yaml": "services:\n  a:\n    image: \"node:${TAG}\"\n"})
    [dep] = run(root, "compose.yaml").dependencies
    assert dep.missing == "image tag set by a variable"


def test_variable_in_image_name_is_unrecognised(write_files):
    root = write_files({"Dockerfile": "FROM ${BASE}:1\n"})
    result = run(root)
    assert result.dependencies == []
    assert result.unrecognised == [Unrecognised(Path("Dockerfile"), "couldn't read the image name in FROM ${BASE}:1")]


def test_broken_compose_unrecognised(write_files):
    root = write_files({"compose.yml": ": :\n"})
    result = run(root, "compose.yml")
    assert result.unrecognised == [Unrecognised(Path("compose.yml"), "couldn't parse compose.yml")]


def test_registered():
    assert any(isinstance(d, DockerDetector) for d in DETECTORS)
