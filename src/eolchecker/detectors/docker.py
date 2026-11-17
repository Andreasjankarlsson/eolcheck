"""Base images from Dockerfiles and compose files."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from ..models import DetectResult, Dependency, Unrecognised
from ..versions import normalise
from . import Context
from ._util import parse_error, read_text, rel

_COMPOSE = re.compile(r"^(docker-)?compose.*\.ya?ml$")
_VAR = re.compile(r"\$\{(\w+)(?:(:?-)([^}]*))?\}|\$(\w+)")
_LEADING_VERSION = re.compile(r"[vV]?(\d+(?:\.\d+)*)")

NO_PIN = "image tag doesn't pin a version"
DIGEST_ONLY = "image pinned by digest only"
BUILD_VARIABLE = "image tag set by a build variable"
COMPOSE_VARIABLE = "image tag set by a variable"


class DockerDetector:
    def applies_to(self, path: Path) -> bool:
        name = path.name
        return (name == "Dockerfile" or name.startswith("Dockerfile.")
                or name.lower().endswith(".dockerfile") or bool(_COMPOSE.match(name)))

    def detect(self, path: Path, ctx: Context) -> DetectResult:
        if _COMPOSE.match(path.name):
            return _detect_compose(path, ctx)
        return _detect_dockerfile(path, ctx)


def split_image(ref: str) -> tuple[str, str | None, str | None]:
    """'host:5000/app:1.2@sha256:x' -> ('host:5000/app', '1.2', 'sha256:x')."""
    name, _, digest = ref.partition("@")
    last = name.rsplit("/", 1)[-1]
    tag = None
    if ":" in last:
        name, _, tag = name.rpartition(":")
    return name, tag or None, digest or None


def _substitute(text: str, variables: dict[str, str]) -> str:
    """Replace $VAR / ${VAR} / ${VAR:-d} / ${VAR-d}; unknown variables stay as written."""
    def repl(m: re.Match[str]) -> str:
        var = m.group(1) or m.group(4)
        if var in variables:
            value = variables[var]
            if not (m.group(2) == ":-" and value == ""):
                return value
        if m.group(2) is not None:
            return m.group(3)
        return m.group(0)
    return _VAR.sub(repl, text)


def _dependency(ref: str, source: Path, variable_reason: str = BUILD_VARIABLE) -> Dependency | None:
    """None when the image name still contains a variable."""
    name, tag, digest = split_image(ref)
    if not name or "$" in name:
        return None
    match = _LEADING_VERSION.match(tag) if tag else None
    version = normalise(match.group(0)) if match else None
    display = tag or digest or "latest"
    missing = None
    if version is None:
        if tag and "$" in tag:
            missing = variable_reason
        elif tag is None and digest:
            missing = DIGEST_ONLY
        else:
            missing = NO_PIN
    return Dependency("Docker", name, version, display, source, tag=tag, missing=missing)


def _logical_lines(text: str) -> list[str]:
    lines: list[str] = []
    buffer = ""
    for raw in text.splitlines():
        stripped = raw.strip()
        if stripped.startswith("#"):
            continue
        if stripped.endswith("\\"):
            buffer += stripped[:-1] + " "
            continue
        lines.append((buffer + stripped).strip())
        buffer = ""
    if buffer.strip():
        lines.append(buffer.strip())
    return lines


def _detect_dockerfile(path: Path, ctx: Context) -> DetectResult:
    result = DetectResult()
    source = rel(path, ctx)
    variables: dict[str, str] = {}
    aliases: set[str] = set()
    for line in _logical_lines(read_text(path)):
        parts = line.split()
        if not parts:
            continue
        keyword = parts[0].upper()
        if keyword == "ARG":
            for token in parts[1:]:
                var, eq, default = token.partition("=")
                if eq:
                    variables.setdefault(var, default.strip("\"'"))
        elif keyword == "FROM":
            args = [p for p in parts[1:] if not p.startswith("--")]
            if not args:
                continue
            ref = _substitute(args[0], variables)
            if len(args) >= 3 and args[1].upper() == "AS":
                alias_after = args[2].lower()
            else:
                alias_after = None
            skip = ref.lower() == "scratch" or ref.lower() in aliases
            if alias_after:
                aliases.add(alias_after)
            if skip:
                continue
            dep = _dependency(ref, source)
            if dep is None:
                result.unrecognised.append(Unrecognised(source, f"couldn't read the image name in FROM {args[0]}"))
            else:
                result.dependencies.append(dep)
    return result


def _detect_compose(path: Path, ctx: Context) -> DetectResult:
    try:
        data = yaml.safe_load(read_text(path))
    except yaml.YAMLError:
        return parse_error(path, ctx)
    if data is None:
        return DetectResult()
    if not isinstance(data, dict):
        return parse_error(path, ctx)
    result = DetectResult()
    source = rel(path, ctx)
    services = data.get("services")
    if not isinstance(services, dict):
        return result
    for service in services.values():
        image = service.get("image") if isinstance(service, dict) else None
        if not isinstance(image, str):
            continue
        dep = _dependency(_substitute(image.strip(), {}), source, COMPOSE_VARIABLE)
        if dep is None:
            result.unrecognised.append(Unrecognised(source, f"couldn't read the image name in image: {image}"))
        else:
            result.dependencies.append(dep)
    return result
