import json
from pathlib import Path

from eolchecker.detectors import Context
from eolchecker.detectors.npm import NpmDetector
from eolchecker.models import Finding, Unrecognised


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
    assert run(root, "frontend/package.json").findings == [
        Finding("Angular", "angular", "16.2.0", "^16.2.0", Path("frontend/package.json"))]


def test_lockfile_wins(write_files):
    lock = {"lockfileVersion": 3, "packages": {"node_modules/@angular/core": {"version": "16.2.12"}}}
    root = write_files({"frontend/package.json": pkg({"@angular/core": "^16.2.0"}),
                        "frontend/package-lock.json": json.dumps(lock)})
    [f] = run(root, "frontend/package.json").findings
    assert (f.version, f.display) == ("16.2.12", "16.2.12")


def test_lockfile_v1(write_files):
    lock = {"lockfileVersion": 1, "dependencies": {"react": {"version": "16.14.0"}}}
    root = write_files({"package.json": pkg({"react": "^16.8.0"}), "package-lock.json": json.dumps(lock)})
    [f] = run(root, "package.json").findings
    assert f.version == "16.14.0"


def test_non_workspace_subapp_ignores_root_lock(write_files):
    lock = {"lockfileVersion": 3, "packages": {"": {}, "node_modules/react": {"version": "18.3.1"}}}
    root = write_files({"package.json": pkg({"react": "^18.2.0"}), "package-lock.json": json.dumps(lock),
                        "legacy/package.json": pkg({"react": "^16.14.0"})})
    [f] = run(root, "legacy/package.json").findings
    assert (f.version, f.display) == ("16.14.0", "^16.14.0")


def test_non_workspace_subapp_ignores_root_v1_lock(write_files):
    lock = {"lockfileVersion": 1, "dependencies": {"react": {"version": "18.3.1"}}}
    root = write_files({"package.json": pkg({"react": "^18.2.0"}), "package-lock.json": json.dumps(lock),
                        "legacy/package.json": pkg({"react": "^16.14.0"})})
    [f] = run(root, "legacy/package.json").findings
    assert f.version == "16.14.0"


def test_lock_at_workspace_root(write_files):
    # npm records workspace members as a "packages" key with their folder path.
    lock = {"lockfileVersion": 3, "packages": {"apps/web": {"name": "web"},
                                               "node_modules/react": {"version": "18.3.1"}}}
    root = write_files({"package-lock.json": json.dumps(lock),
                        "apps/web/package.json": pkg({"react": "^18.2.0"})})
    [f] = run(root, "apps/web/package.json").findings
    assert (f.version, f.source) == ("18.3.1", Path("apps/web/package.json"))


def test_yarn_classic_lock(write_files):
    yarn = ('# yarn lockfile v1\n\n'
            'react@^17.0.0:\n  version "17.0.1"\n\n'
            '"react@^18.2.0", react@^18.0.0:\n  version "18.2.0"\n  resolved "x"\n')
    root = write_files({"package.json": pkg({"react": "^18.2.0"}), "yarn.lock": yarn})
    [f] = run(root, "package.json").findings
    assert f.version == "18.2.0"


def test_yarn_berry_lock(write_files):
    yarn = '__metadata:\n  version: 6\n\n"react@npm:^18.2.0":\n  version: 18.3.1\n  resolution: "react@npm:18.3.1"\n'
    root = write_files({"package.json": pkg({"react": "^18.2.0"}), "yarn.lock": yarn})
    [f] = run(root, "package.json").findings
    assert f.version == "18.3.1"


def test_pnpm_lock(write_files):
    pnpm = ("lockfileVersion: '9.0'\nimporters:\n  apps/web:\n    dependencies:\n"
            "      next:\n        specifier: ^14.1.0\n        version: 14.2.3(react@18.3.1)\n")
    root = write_files({"pnpm-lock.yaml": pnpm, "apps/web/package.json": pkg({"next": "^14.1.0"})})
    [f] = run(root, "apps/web/package.json").findings
    assert (f.component, f.version) == ("Next.js", "14.2.3")


def test_angularjs_react_next_and_engines(write_files):
    root = write_files({"package.json": pkg({"angular": "1.8.3", "react": "18.2.0"},
                                            dev={"next": "14.0.0"}, engines={"node": ">=18"})})
    found = {f.component: f for f in run(root, "package.json").findings}
    assert set(found) == {"AngularJS", "React", "Next.js", "Node.js"}
    assert (found["Node.js"].version, found["Node.js"].display) == ("18", ">=18")
    assert found["AngularJS"].version == "1.8.3"


def test_latest_tag_is_unrecognised(write_files):
    root = write_files({"package.json": pkg({"next": "latest"})})
    result = run(root, "package.json")
    assert result.findings == []
    assert result.unrecognised == [Unrecognised(Path("package.json"), "couldn't read the Next.js version")]


def test_package_json_without_frameworks_is_silent(write_files):
    root = write_files({"package.json": pkg({"lodash": "^4"})})
    result = run(root, "package.json")
    assert (result.findings, result.unrecognised) == ([], [])


def test_nvmrc(write_files):
    root = write_files({"web/.nvmrc": "v18.17.0\n"})
    assert run(root, "web/.nvmrc").findings == [
        Finding("Node.js", "nodejs", "18.17.0", "18.17.0", Path("web/.nvmrc"))]


def test_node_version_file(write_files):
    root = write_files({".node-version": "20\n"})
    [f] = run(root, ".node-version").findings
    assert f.version == "20"


def test_nvmrc_lts_alias_unrecognised(write_files):
    root = write_files({".nvmrc": "lts/hydrogen\n"})
    assert run(root, ".nvmrc").unrecognised == [Unrecognised(Path(".nvmrc"), "couldn't read the Node.js version")]


def test_bom_is_accepted(write_files):
    root = write_files({"package.json": "﻿" + pkg({"react": "18.2.0"})})
    [f] = run(root, "package.json").findings
    assert f.version == "18.2.0"


def test_broken_json_unrecognised(write_files):
    root = write_files({"package.json": "{ not json"})
    assert run(root, "package.json").unrecognised == [Unrecognised(Path("package.json"), "couldn't parse package.json")]


def test_registered():
    from eolchecker.detectors import DETECTORS
    assert any(isinstance(d, NpmDetector) for d in DETECTORS)
