import json
from pathlib import Path

from eolchecker.detectors import Context
from eolchecker.detectors.npm import NpmDetector
from eolchecker.models import Dependency, Finding, Unrecognised

from ..fakes import index, product


def run(root: Path, rel: str):
    return NpmDetector().detect(root / rel, Context(root))


def pkg(deps=None, dev=None, engines=None):
    data = {}
    if deps:
        data["dependencies"] = deps
    if dev:
        data["devDependencies"] = dev
    if engines:
        data["engines"] = engines
    return json.dumps(data)


def test_applies_to():
    d = NpmDetector()
    assert d.applies_to(Path("a/package.json"))
    assert d.applies_to(Path(".nvmrc"))
    assert d.applies_to(Path(".node-version"))
    assert not d.applies_to(Path("package-lock.json"))


def test_angular_from_package_json_without_lock(write_files):
    root = write_files({"frontend/package.json": pkg({"@angular/core": "^16.2.0"})})
    assert run(root, "frontend/package.json").dependencies == [
        Dependency("npm:@angular/core", "@angular/core", "16.2.0", "^16.2.0", Path("frontend/package.json"))]


def test_lockfile_wins(write_files):
    lock = {"lockfileVersion": 3, "packages": {"node_modules/@angular/core": {"version": "16.2.12"}}}
    root = write_files({"frontend/package.json": pkg({"@angular/core": "^16.2.0"}),
                        "frontend/package-lock.json": json.dumps(lock)})
    [f] = run(root, "frontend/package.json").dependencies
    assert (f.version, f.display) == ("16.2.12", "16.2.12")


def test_lockfile_v1(write_files):
    lock = {"lockfileVersion": 1, "dependencies": {"react": {"version": "16.14.0"}}}
    root = write_files({"package.json": pkg({"react": "^16.8.0"}), "package-lock.json": json.dumps(lock)})
    [f] = run(root, "package.json").dependencies
    assert f.version == "16.14.0"


def test_non_workspace_subapp_ignores_root_lock(write_files):
    lock = {"lockfileVersion": 3, "packages": {"": {}, "node_modules/react": {"version": "18.3.1"}}}
    root = write_files({"package.json": pkg({"react": "^18.2.0"}), "package-lock.json": json.dumps(lock),
                        "legacy/package.json": pkg({"react": "^16.14.0"})})
    [f] = run(root, "legacy/package.json").dependencies
    assert (f.version, f.display) == ("16.14.0", "^16.14.0")


def test_non_workspace_subapp_ignores_root_v1_lock(write_files):
    lock = {"lockfileVersion": 1, "dependencies": {"react": {"version": "18.3.1"}}}
    root = write_files({"package.json": pkg({"react": "^18.2.0"}), "package-lock.json": json.dumps(lock),
                        "legacy/package.json": pkg({"react": "^16.14.0"})})
    [f] = run(root, "legacy/package.json").dependencies
    assert f.version == "16.14.0"


def test_lock_at_workspace_root(write_files):
    # npm records workspace members as a "packages" key with their folder path.
    lock = {"lockfileVersion": 3, "packages": {"apps/web": {"name": "web"},
                                               "node_modules/react": {"version": "18.3.1"}}}
    root = write_files({"package-lock.json": json.dumps(lock),
                        "apps/web/package.json": pkg({"react": "^18.2.0"})})
    [f] = run(root, "apps/web/package.json").dependencies
    assert (f.version, f.source) == ("18.3.1", Path("apps/web/package.json"))


def test_yarn_classic_lock(write_files):
    yarn = ('# yarn lockfile v1\n\n'
            'react@^17.0.0:\n  version "17.0.1"\n\n'
            '"react@^18.2.0", react@^18.0.0:\n  version "18.2.0"\n  resolved "x"\n')
    root = write_files({"package.json": pkg({"react": "^18.2.0"}), "yarn.lock": yarn})
    [f] = run(root, "package.json").dependencies
    assert f.version == "18.2.0"


def test_yarn_berry_lock(write_files):
    yarn = '__metadata:\n  version: 6\n\n"react@npm:^18.2.0":\n  version: 18.3.1\n  resolution: "react@npm:18.3.1"\n'
    root = write_files({"package.json": pkg({"react": "^18.2.0"}), "yarn.lock": yarn})
    [f] = run(root, "package.json").dependencies
    assert f.version == "18.3.1"


def _count_reads(monkeypatch, name):
    import eolchecker.detectors.npm as npm
    calls = []
    real = npm.read_text

    def counting(path):
        if path.name == name:
            calls.append(path)
        return real(path)
    monkeypatch.setattr(npm, "read_text", counting)
    return calls


def test_yarn_lock_read_once_for_several_dependencies(write_files, monkeypatch):
    yarn = ('react@^18.2.0:\n  version "18.2.0"\n\n'
            'react-dom@^18.2.0:\n  version "18.2.1"\n')
    root = write_files({"package.json": pkg({"react": "^18.2.0", "react-dom": "^18.2.0"}), "yarn.lock": yarn})
    calls = _count_reads(monkeypatch, "yarn.lock")
    assert [d.version for d in run(root, "package.json").dependencies] == ["18.2.0", "18.2.1"]
    assert len(calls) == 1


def test_root_lock_read_once_per_scan_for_workspaces(write_files, monkeypatch):
    lock = {"lockfileVersion": 3, "packages": {"apps/a": {}, "apps/b": {},
                                               "node_modules/react": {"version": "18.3.1"}}}
    root = write_files({"package-lock.json": json.dumps(lock),
                        "apps/a/package.json": pkg({"react": "^18.2.0"}),
                        "apps/b/package.json": pkg({"react": "^18.2.0"})})
    calls = _count_reads(monkeypatch, "package-lock.json")
    det, ctx = NpmDetector(), Context(root)
    versions = [d.version for rel in ("apps/a/package.json", "apps/b/package.json")
                for d in det.detect(root / rel, ctx).dependencies]
    assert versions == ["18.3.1", "18.3.1"]
    assert len(calls) == 1
    det.detect(root / "apps/a/package.json", Context(root))  # a new scan reads the lock again
    assert len(calls) == 2


def test_pnpm_lock(write_files):
    pnpm = ("lockfileVersion: '9.0'\nimporters:\n  apps/web:\n    dependencies:\n"
            "      next:\n        specifier: ^14.1.0\n        version: 14.2.3(react@18.3.1)\n")
    root = write_files({"pnpm-lock.yaml": pnpm, "apps/web/package.json": pkg({"next": "^14.1.0"})})
    [f] = run(root, "apps/web/package.json").dependencies
    assert (f.name, f.version) == ("next", "14.2.3")


def test_angularjs_react_next_and_engines(write_files):
    root = write_files({"package.json": pkg({"angular": "1.8.3", "react": "18.2.0"},
                                            dev={"next": "14.0.0"}, engines={"node": ">=18"})})
    result = run(root, "package.json")
    found = {d.name: d for d in result.dependencies}
    assert set(found) == {"angular", "react", "next"}
    assert found["angular"].version == "1.8.3"
    [node] = result.findings
    assert (node.component, node.version, node.display) == ("Node.js", "18", ">=18")


def test_latest_tag_is_unrecognised(write_files):
    root = write_files({"package.json": pkg({"next": "latest"})})
    result = run(root, "package.json")
    assert result.findings == []
    assert result.unrecognised == [Unrecognised(Path("package.json"), "couldn't read the Next.js version")]


def test_package_json_without_dependencies_is_silent(write_files):
    root = write_files({"package.json": json.dumps({"name": "x"})})
    result = run(root, "package.json")
    assert (result.findings, result.dependencies, result.unrecognised) == ([], [], [])


def test_every_section_is_read(write_files):
    data = {"peerDependencies": {"c": "3.0.0"}, "devDependencies": {"b": "2.0.0"}, "dependencies": {"a": "1.0.0"}}
    root = write_files({"package.json": json.dumps(data)})
    assert [(d.name, d.version) for d in run(root, "package.json").dependencies] == [
        ("a", "1.0.0"), ("b", "2.0.0"), ("c", "3.0.0")]


def test_key_is_lower_case_and_name_as_written(write_files):
    root = write_files({"package.json": pkg({"Left-Pad": "1.0.0"})})
    [d] = run(root, "package.json").dependencies
    assert (d.key, d.name) == ("npm:left-pad", "Left-Pad")


def test_untracked_with_unreadable_version_is_silent(write_files):
    root = write_files({"package.json": pkg({"left-pad": "git+https://example.com/x.git"})})
    result = run(root, "package.json")
    assert result.dependencies == [Dependency("npm:left-pad", "left-pad", None, None, Path("package.json"))]
    assert result.unrecognised == []


def test_sibling_version_covers_unreadable_one(write_files):
    idx = index(product("angular", "Angular", ["pkg:npm/%40angular/core", "pkg:npm/%40angular/common"]))
    root = write_files({"package.json": pkg({"@angular/core": "16.2.0", "@angular/common": "file:../x"})})
    result = NpmDetector().detect(root / "package.json", Context(root, index=idx))
    assert len(result.dependencies) == 2
    assert result.unrecognised == []


def test_unreadable_without_sibling_is_one_gap_per_component(write_files):
    idx = index(product("angular", "Angular", ["pkg:npm/%40angular/core", "pkg:npm/%40angular/common"]))
    root = write_files({"package.json": pkg({"@angular/core": "latest", "@angular/common": "file:../x"})})
    result = NpmDetector().detect(root / "package.json", Context(root, index=idx))
    assert result.unrecognised == [Unrecognised(Path("package.json"), "couldn't read the Angular version")]


def test_node_engines_origin(write_files):
    root = write_files({"package.json": pkg(engines={"node": ">=18"})})
    [f] = run(root, "package.json").findings
    assert f.origin == "engines.node"


def test_nvmrc(write_files):
    root = write_files({"web/.nvmrc": "v18.17.0\n"})
    assert run(root, "web/.nvmrc").findings == [
        Finding("Node.js", "nodejs", "18.17.0", "18.17.0", Path("web/.nvmrc"), origin=".nvmrc")]


def test_node_version_file(write_files):
    root = write_files({".node-version": "20\n"})
    [f] = run(root, ".node-version").findings
    assert (f.version, f.origin) == ("20", ".node-version")


def test_nvmrc_lts_alias_unrecognised(write_files):
    root = write_files({".nvmrc": "lts/hydrogen\n"})
    assert run(root, ".nvmrc").unrecognised == [Unrecognised(Path(".nvmrc"), "couldn't read the Node.js version")]


def test_bom_is_accepted(write_files):
    root = write_files({"package.json": "﻿" + pkg({"react": "18.2.0"})})
    [f] = run(root, "package.json").dependencies
    assert f.version == "18.2.0"


def test_broken_json_unrecognised(write_files):
    root = write_files({"package.json": "{ not json"})
    assert run(root, "package.json").unrecognised == [Unrecognised(Path("package.json"), "couldn't parse package.json")]


def test_registered():
    from eolchecker.detectors import DETECTORS
    assert any(isinstance(d, NpmDetector) for d in DETECTORS)
